from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal, cast
from urllib.parse import quote, urlsplit

from digital_bast.config import get_settings
from digital_bast.domain.completion import DateRange

_TOKEN_VERSION: Final = 2
_DEFAULT_TTL_SECONDS: Final = 30 * 60
_MAX_PMO_TTL_SECONDS: Final = 7 * 24 * 60 * 60
_MAX_TOKEN_LENGTH: Final = 4096
_MAX_PERIOD_DAYS: Final = 31
_ALLOWED_TABS: Final = frozenset({"attendance", "tasks"})
_BINDING_CONTEXT: Final = b"digital-bast:talent-mobile:binding:v1:"
_PMO_ISSUER_CONTEXT: Final = b"digital-bast:talent-mobile:pmo-issuer:v1:"
type TalentMobileAccessMode = Literal["whatsapp", "pmo"]


@dataclass(frozen=True, slots=True)
class TalentMobileClaims:
    employee_id: str
    binding_tag: str | None
    period: DateRange
    expires_at: datetime
    access_mode: TalentMobileAccessMode = "whatsapp"
    actor_tag: str | None = None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def talent_mobile_binding_tag(secret: str, jid: str) -> str:
    """Non-reversible binding fingerprint used inside short-lived bot links."""
    digest = hmac.new(
        secret.encode(),
        _BINDING_CONTEXT + jid.encode(),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest[:18])


def talent_mobile_binding_matches(secret: str, jid: str, supplied_tag: str) -> bool:
    expected = talent_mobile_binding_tag(secret, jid)
    return hmac.compare_digest(expected, supplied_tag)


def _pmo_actor_tag(secret: str, issuer: str) -> str:
    normalized = issuer.strip().casefold()
    digest = hmac.new(
        secret.encode(),
        _PMO_ISSUER_CONTEXT + normalized.encode(),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest[:18])


def _issue_payload(secret: str, payload: dict[str, object]) -> str:
    encoded = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def issue_talent_mobile_token(  # noqa: PLR0913
    secret: str,
    employee_id: str,
    jid: str,
    period: DateRange,
    *,
    now: datetime | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    return _issue_payload(
        secret,
        {
            "v": _TOKEN_VERSION,
            "sub": employee_id,
            "bind": talent_mobile_binding_tag(secret, jid),
            "s": period.start.isoformat(),
            "e": period.end.isoformat(),
            "exp": int(expires_at.timestamp()),
        },
    )


def issue_pmo_talent_mobile_token(  # noqa: PLR0913
    secret: str,
    employee_id: str,
    issuer: str,
    period: DateRange,
    *,
    now: datetime | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Issue a bounded bearer grant from authenticated PMO Web.

    PMO-issued links deliberately do not depend on WhatsApp binding. The token
    remains signed, employee-bound, period-bound and time-limited. The issuer is
    represented only by a keyed non-reversible audit tag, never by raw email.
    """
    normalized_issuer = issuer.strip()
    if (
        not normalized_issuer
        or ttl_seconds <= 0
        or ttl_seconds > _MAX_PMO_TTL_SECONDS
    ):
        raise ValueError
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    return _issue_payload(
        secret,
        {
            "v": _TOKEN_VERSION,
            "sub": employee_id,
            "grant": "pmo",
            "actor": _pmo_actor_tag(secret, normalized_issuer),
            "s": period.start.isoformat(),
            "e": period.end.isoformat(),
            "exp": int(expires_at.timestamp()),
        },
    )


def _parse_period(start: object, end: object) -> DateRange | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        period = DateRange(date.fromisoformat(start), date.fromisoformat(end))
    except (ValueError, TypeError):
        return None
    if period.start.year != period.end.year or period.start.month != period.end.month:
        return None
    if (period.end - period.start).days + 1 > _MAX_PERIOD_DAYS:
        return None
    return period


def verify_talent_mobile_token(  # noqa: C901, PLR0911, PLR0912
    secret: str,
    token: str,
    *,
    now: datetime | None = None,
) -> TalentMobileClaims | None:
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(supplied_signature)):
            return None
        decoded: object = json.loads(_b64decode(encoded))
        if not isinstance(decoded, dict):
            return None
        raw = cast("dict[str, object]", decoded)
        if raw.get("v") != _TOKEN_VERSION:
            return None
        employee_id = raw.get("sub")
        exp = raw.get("exp")
        if not isinstance(employee_id, str) or not employee_id:
            return None
        if not isinstance(exp, int):
            return None
        period = _parse_period(raw.get("s"), raw.get("e"))
        if period is None:
            return None
        expires_at = datetime.fromtimestamp(exp, tz=UTC)
        grant = raw.get("grant")
        binding_tag: str | None = None
        actor_tag: str | None = None
        access_mode: TalentMobileAccessMode
        if grant is None:
            raw_binding = raw.get("bind")
            if not isinstance(raw_binding, str) or not raw_binding:
                return None
            binding_tag = raw_binding
            access_mode = "whatsapp"
        elif grant == "pmo":
            raw_actor = raw.get("actor")
            if not isinstance(raw_actor, str) or not raw_actor:
                return None
            actor_tag = raw_actor
            access_mode = "pmo"
        else:
            return None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if expires_at <= current:
        return None
    return TalentMobileClaims(
        employee_id,
        binding_tag,
        period,
        expires_at,
        access_mode,
        actor_tag,
    )


def _public_url(public_url: str | None) -> str | None:
    resolved = (
        (public_url if public_url is not None else os.environ.get("TALENTOPS_PUBLIC_URL", ""))
        .strip()
        .rstrip("/")
    )
    if not resolved:
        return None
    parsed = urlsplit(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return resolved


def _session_secret() -> str | None:
    try:
        settings = get_settings()
    except (OSError, ValueError):
        return None
    if settings.session_secret is None:
        return None
    return settings.session_secret.get_secret_value()


def configured_talent_mobile_url(
    employee_id: str,
    jid: str,
    period: DateRange,
    tab: Literal["attendance", "tasks"],
    *,
    public_url: str | None = None,
) -> str | None:
    resolved_public_url = _public_url(public_url)
    secret = _session_secret()
    if resolved_public_url is None or secret is None or tab not in _ALLOWED_TABS:
        return None
    token = issue_talent_mobile_token(secret, employee_id, jid, period)
    return f"{resolved_public_url}/talent/mobile?t={quote(token, safe='')}&tab={tab}"


def configured_pmo_talent_mobile_url(  # noqa: PLR0913
    employee_id: str,
    issuer: str,
    period: DateRange,
    tab: Literal["attendance", "tasks"],
    *,
    public_url: str | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str | None:
    resolved_public_url = _public_url(public_url)
    secret = _session_secret()
    if resolved_public_url is None or secret is None or tab not in _ALLOWED_TABS:
        return None
    try:
        token = issue_pmo_talent_mobile_token(
            secret,
            employee_id,
            issuer,
            period,
            ttl_seconds=ttl_seconds,
        )
    except ValueError:
        return None
    return f"{resolved_public_url}/talent/mobile?t={quote(token, safe='')}&tab={tab}"
