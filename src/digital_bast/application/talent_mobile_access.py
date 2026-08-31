from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from urllib.parse import quote, urlsplit

from digital_bast.config import get_settings
from digital_bast.domain.completion import DateRange

_TOKEN_VERSION: Final = 1
_DEFAULT_TTL_SECONDS: Final = 30 * 60
_MAX_TOKEN_LENGTH: Final = 4096
_ALLOWED_TABS: Final = frozenset({"attendance", "tasks"})


@dataclass(frozen=True, slots=True)
class TalentMobileClaims:
    employee_id: str
    jid: str
    year: int
    month: int
    expires_at: datetime


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_talent_mobile_token(
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
            "jid": jid,
            "y": period.start.year,
            "m": period.start.month,
            "exp": int(expires_at.timestamp()),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_talent_mobile_token(
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
        raw = json.loads(_b64decode(encoded))
        if not isinstance(raw, dict) or raw.get("v") != _TOKEN_VERSION:
            return None
        employee_id = raw.get("sub")
        jid = raw.get("jid")
        year = raw.get("y")
        month = raw.get("m")
        exp = raw.get("exp")
        if not isinstance(employee_id, str) or not employee_id:
            return None
        if not isinstance(jid, str) or not jid:
            return None
        if not isinstance(year, int) or not 2020 <= year <= 2100:
            return None
        if not isinstance(month, int) or not 1 <= month <= 12:
            return None
        if not isinstance(exp, int):
            return None
        expires_at = datetime.fromtimestamp(exp, tz=UTC)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if expires_at <= current:
        return None
    return TalentMobileClaims(employee_id, jid, year, month, expires_at)


def configured_talent_mobile_url(
    employee_id: str,
    jid: str,
    period: DateRange,
    tab: Literal["attendance", "tasks"],
) -> str | None:
    public_url = os.environ.get("TALENTOPS_PUBLIC_URL", "").strip().rstrip("/")
    if not public_url or tab not in _ALLOWED_TABS:
        return None
    parsed = urlsplit(public_url)
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
    return f"{public_url}/talent/mobile?t={quote(token, safe='')}&tab={tab}"
