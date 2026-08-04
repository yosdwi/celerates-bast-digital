from __future__ import annotations

from typing import final

import bcrypt
import psycopg
from anyio.to_thread import run_sync

from digital_bast.web.contracts import AuthenticatedUser
from digital_bast.web.errors import AuthenticationUnavailableError

_ADMIN_ROLES = frozenset({"owner", "super", "org-level-creator"})

_SELECT_OWNER = """
    SELECT u.id, u.email, u.password, u.display_name, u.user_name,
           u.blocked, u.is_deleted, bu.roles AS base_role
    FROM nc_users_v2 u
    LEFT JOIN nc_base_users_v2 bu ON u.id = bu.fk_user_id AND bu.base_id = %s
    WHERE u.email = %s
      AND (u.blocked IS NULL OR u.blocked = FALSE)
      AND (u.is_deleted IS NULL OR u.is_deleted = FALSE)
"""


def _active_roles(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(role.strip().casefold() for role in value.split(","))


@final
class NocoDBPostgresOwnerAuthenticator:
    def __init__(self, dsn: str, base_id: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._base_id = base_id
        self._connect_timeout_seconds = connect_timeout_seconds

    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        try:
            return await run_sync(self._authenticate_owner, email, password)
        except psycopg.Error as error:
            raise AuthenticationUnavailableError(service="NocoDB Postgres") from error

    async def ready(self) -> bool:
        try:
            return await run_sync(self._ready)
        except psycopg.Error:
            return False

    def _authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        with (
            psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds) as connection,
            connection.cursor() as cursor,
        ):
            _ = cursor.execute(_SELECT_OWNER, (self._base_id, email))
            row = cursor.fetchone()
        if row is None:
            return None
        (
            user_id,
            user_email,
            stored_password,
            display_name,
            user_name,
            _blocked,
            _is_deleted,
            base_role,
        ) = row
        if _ADMIN_ROLES.isdisjoint(_active_roles(base_role)):
            return None
        if not stored_password or not _verify_password(password, stored_password):
            return None
        return AuthenticatedUser(
            id=user_id,
            email=user_email,
            name=display_name or user_name or user_email.partition("@")[0],
            role="owner",
        )

    def _ready(self) -> bool:
        with (
            psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds) as connection,
            connection.cursor() as cursor,
        ):
            _ = cursor.execute("SELECT 1")
            return cursor.fetchone() is not None


def _verify_password(plain_password: str, stored_hash: str) -> bool:
    if not stored_hash.startswith(("$2a$", "$2b$")):
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False
