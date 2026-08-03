import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal

from fastapi import Form, Header, HTTPException, Request, status
from starlette.responses import Response

from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord, SessionStore
from digital_bast.web.sessions import session_is_expired


@dataclass(frozen=True, slots=True)
class CookieSettings:
    name: str = "digital_bast_session"
    ttl_seconds: int = 86_400
    secure: bool = True
    same_site: Literal["lax", "strict", "none"] = "strict"
    path: str = "/"


async def load_session(
    request: Request,
    store: SessionStore,
    settings: CookieSettings,
    now: Callable[[], datetime],
) -> tuple[SessionId, SessionRecord] | None:
    raw_session_id = request.cookies.get(settings.name)
    if raw_session_id is None or len(raw_session_id) > MAX_SESSION_ID_LENGTH:
        return None
    session_id = SessionId(raw_session_id)
    record = await store.get(session_id)
    if record is None:
        return None
    if session_is_expired(record, now()):
        await store.delete(session_id)
        return None
    return session_id, record


async def require_session(
    request: Request,
    store: SessionStore,
    settings: CookieSettings,
    now: Callable[[], datetime],
    api: bool,
) -> tuple[SessionId, SessionRecord]:
    loaded = await load_session(request, store, settings, now)
    if loaded is not None:
        return loaded
    headers = {} if api else {"Location": "/admin/login"}
    code = status.HTTP_401_UNAUTHORIZED if api else status.HTTP_303_SEE_OTHER
    raise HTTPException(status_code=code, detail="Authentication required", headers=headers)


def verify_csrf(record: SessionRecord, submitted: str | None) -> None:
    if submitted is None or not secrets.compare_digest(record.csrf_token, submitted):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


def set_session_cookie(response: Response, session_id: SessionId, settings: CookieSettings) -> None:
    response.set_cookie(
        key=settings.name,
        value=session_id,
        max_age=settings.ttl_seconds,
        secure=settings.secure,
        httponly=True,
        samesite=settings.same_site,
        path=settings.path,
    )


def clear_session_cookie(response: Response, settings: CookieSettings) -> None:
    response.delete_cookie(
        key=settings.name,
        secure=settings.secure,
        httponly=True,
        samesite=settings.same_site,
        path=settings.path,
    )


def new_session_record(user: AuthenticatedUser, now: datetime, ttl_seconds: int) -> SessionRecord:
    normalized = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return SessionRecord(
        user=user,
        csrf_token=secrets.token_urlsafe(32),
        created_at=normalized,
        expires_at=normalized + timedelta(seconds=ttl_seconds),
    )


FormCsrf = Annotated[str | None, Form(alias="_csrf_token")]
HeaderCsrf = Annotated[str | None, Header(alias="X-CSRF-Token")]
MAX_SESSION_ID_LENGTH: Final = 256
