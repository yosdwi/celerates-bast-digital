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
_MAX_TOKEN_LENGTH: Final = 4096
_MAX_PERIOD_DAYS: Final = 31
_ALLOWED_TABS: Final = frozenset({"attendance", "tasks"})
_BINDING_CONTEXT: Final = b"digital-bast:talent-mobile:binding:v1:"


@dataclass(frozen=True, slots=True)
class TalentMobileClaims:
    employee_id: str
    binding_tag: str
    period: DateRange
    expires_at: datetime


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def talent_mobile_binding_tag(secret: str, jid: str) -> str:
    """Non-reversible binding fingerprint used inside short-lived links.

    The WhatsApp JID commonly contains the talent's phone number. Keep it out
    of the URL/token payload entirely; the web API resolves the current JID
    from the durable binding and compares this keyed fingerprint instead.
    """
    digest = hmac.new(
        secret.encode(),
        _BINDING_CONTEXT + jid.encode(),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest[:18])


def talent_mobile_binding_matches(secret: str, jid: str, supplied_tag: str) -> bool:
    expected = talent_mobile_binding_tag(secret, jid)
    return hmac.compare_digest(expected, supplied_tag)


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
    payload = json.dumps(
        {
            "v": _TOKEN_VERSION,
            "sub": employee_id,
            "bind": talent_mobile_binding_tag(secret, jid),
            "s": period.start.isoformat(),
            "e": period.end.isoformat(),
            "exp": int(expires_at.timestamp()),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


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


def verify_talent_mobile_token(  # noqa: C901, PLR0911
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
        binding_tag = raw.get("bind")
        exp = raw.get("exp")
        if not isinstance(employee_id, str) or not employee_id:
            return None
        if not isinstance(binding_tag, str) or not binding_tag:
            return None
        if not isinstance(exp, int):
            return None
        period = _parse_period(raw.get("s"), raw.get("e"))
        if period is None:
            return None
        expires_at = datetime.fromtimestamp(exp, tz=UTC)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if expires_at <= current:
        return None
    return TalentMobileClaims(employee_id, binding_tag, period, expires_at)


def configured_talent_mobile_url(
    employee_id: str,
    jid: str,
    period: DateRange,
    tab: Literal["attendance", "tasks"],
    *,
    public_url: str | None = None,
) -> str | None:
    resolved_public_url = (
        (public_url if public_url is not None else os.environ.get("TALENTOPS_PUBLIC_URL", ""))
        .strip()
        .rstrip("/")
    )
    if not resolved_public_url or tab not in _ALLOWED_TABS:
        return None
    parsed = urlsplit(resolved_public_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    try:
        settings = get_settings()
    except (OSError, ValueError):
        return None
    if settings.session_secret is None:
        return None
    token = issue_talent_mobile_token(
        settings.session_secret.get_secret_value(),
        employee_id,
        jid,
        period,
    )
    return f"{resolved_public_url}/talent/mobile?t={quote(token, safe='')}&tab={tab}"
