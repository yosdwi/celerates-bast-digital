import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from digital_bast.web.contracts import OwnerAuthenticator, SessionStore, WebBackend
from digital_bast.web.security import CookieSettings


@dataclass(frozen=True, slots=True)
class WebDependencies:
    authenticator: OwnerAuthenticator
    sessions: SessionStore
    backend: WebBackend
    cookie: CookieSettings
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    session_id: Callable[[], str] = lambda: secrets.token_urlsafe(32)
