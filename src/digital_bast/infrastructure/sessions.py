from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Protocol, final

from pydantic import BaseModel, ConfigDict, ValidationError
from redis import Redis
from redis.exceptions import RedisError

from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.infrastructure.redis_url import parse_redis_url


class SessionBackend(Protocol):
    def set(self, name: str, value: str, *, ex: int) -> bool | None: ...

    def getex(self, name: str, *, ex: int) -> bytes | str | None: ...

    def delete(self, *names: str) -> int: ...


class _SessionPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    user_id: str
    roles: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UserSession:
    session_id: str
    user_id: str
    roles: tuple[str, ...]
    created_at: datetime


@final
class RedisSessionStore:
    def __init__(
        self,
        backend: SessionBackend,
        ttl_seconds: int,
        namespace: str = "bast:session",
    ) -> None:
        self._backend: SessionBackend = backend
        self._ttl_seconds: int = ttl_seconds
        self._namespace: str = namespace

    def create(self, user_id: str, roles: tuple[str, ...]) -> UserSession:
        session = UserSession(
            session_id=secrets.token_urlsafe(32),
            user_id=user_id,
            roles=roles,
            created_at=datetime.now(UTC),
        )
        payload = _SessionPayload(
            user_id=session.user_id,
            roles=session.roles,
            created_at=session.created_at,
        )
        try:
            _ = self._backend.set(
                self._key(session.session_id),
                payload.model_dump_json(),
                ex=self._ttl_seconds,
            )
        except RedisError as error:
            raise InfrastructureError(service="redis", operation="create_session") from error
        return session

    def get(self, session_id: str) -> UserSession | None:
        try:
            raw = self._backend.getex(self._key(session_id), ex=self._ttl_seconds)
        except RedisError as error:
            raise InfrastructureError(service="redis", operation="get_session") from error
        if raw is None:
            return None
        try:
            payload = _SessionPayload.model_validate_json(raw)
        except ValidationError as error:
            _ = self.delete(session_id)
            raise InfrastructureError(service="redis", operation="parse_session") from error
        return UserSession(
            session_id=session_id,
            user_id=payload.user_id,
            roles=payload.roles,
            created_at=payload.created_at,
        )

    def delete(self, session_id: str) -> bool:
        try:
            return self._backend.delete(self._key(session_id)) == 1
        except RedisError as error:
            raise InfrastructureError(service="redis", operation="delete_session") from error

    def _key(self, session_id: str) -> str:
        return f"{self._namespace}:{session_id}"


def create_redis_backend(
    url: str,
    timeout_seconds: float = 5.0,
    password: str | None = None,
) -> Redis:
    endpoint = parse_redis_url(url)
    return Redis(
        host=endpoint.host,
        port=endpoint.port,
        db=endpoint.database,
        username=endpoint.username,
        password=password if password is not None else endpoint.password,
        ssl=endpoint.ssl,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        health_check_interval=30,
        decode_responses=False,
    )
