import json
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord
from digital_bast.web.errors import SessionUnavailableError


class RedisSessionStore:
    def __init__(self, client: Redis, key_prefix: str = "digital-bast:session:") -> None:
        self._client = client
        self._key_prefix = key_prefix

    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        payload = json.dumps(
            {
                "user": {
                    "id": record.user.id,
                    "email": record.user.email,
                    "name": record.user.name,
                    "role": record.user.role,
                },
                "csrf_token": record.csrf_token,
                "created_at": record.created_at.isoformat(),
                "expires_at": record.expires_at.isoformat(),
            },
            separators=(",", ":"),
        )
        try:
            await self._client.set(self._key(session_id), payload, ex=ttl_seconds)
        except RedisError as exc:
            raise SessionUnavailableError(operation="create") from exc

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        try:
            raw = await self._client.get(self._key(session_id))
        except RedisError as exc:
            raise SessionUnavailableError(operation="read") from exc
        if raw is None:
            return None
        decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(decoded)
        user = payload["user"]
        return SessionRecord(
            user=AuthenticatedUser(
                id=str(user["id"]),
                email=str(user["email"]),
                name=str(user["name"]),
                role=str(user["role"]),
            ),
            csrf_token=str(payload["csrf_token"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        )

    async def delete(self, session_id: SessionId) -> None:
        try:
            await self._client.delete(self._key(session_id))
        except RedisError as exc:
            raise SessionUnavailableError(operation="delete") from exc

    async def ready(self) -> bool:
        try:
            _ = await self._client.get(f"{self._key_prefix}healthcheck")
        except RedisError:
            return False
        return True

    def _key(self, session_id: SessionId) -> str:
        return f"{self._key_prefix}{session_id}"


def session_is_expired(record: SessionRecord, now: datetime) -> bool:
    normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    normalized_expiry = (
        record.expires_at
        if record.expires_at.tzinfo is not None
        else record.expires_at.replace(tzinfo=UTC)
    )
    return normalized_now >= normalized_expiry
