from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

import psycopg
from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError

DEFAULT_PMO_LINK_TTL_DAYS: Final = 7
MIN_PMO_LINK_TTL_DAYS: Final = 1
MAX_PMO_LINK_TTL_DAYS: Final = 7


@dataclass(frozen=True, slots=True)
class TalentMobileLinkPolicy:
    scope_key: str
    ttl_days: int


def _validate_ttl_days(value: int) -> int:
    if value < MIN_PMO_LINK_TTL_DAYS or value > MAX_PMO_LINK_TTL_DAYS:
        raise ValueError
    return value


@final
class TalentMobileLinkPolicyService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def get(self, scope_key: str = "default") -> TalentMobileLinkPolicy:
        return await run_sync(self._get, scope_key)

    async def save(
        self,
        *,
        scope_key: str,
        ttl_days: int,
        actor: str,
    ) -> TalentMobileLinkPolicy:
        return await run_sync(self._save, scope_key, ttl_days, actor)

    def _get(self, scope_key: str) -> TalentMobileLinkPolicy:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT talent_mobile_link_ttl_days
                    FROM workflow_notification_settings
                    WHERE scope_key = %s
                    """,
                    (scope_key,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="talent_mobile_link_policy",
            ) from error
        ttl_days = DEFAULT_PMO_LINK_TTL_DAYS if row is None else int(row[0])
        return TalentMobileLinkPolicy(scope_key=scope_key, ttl_days=ttl_days)

    def _save(
        self,
        scope_key: str,
        ttl_days: int,
        actor: str,
    ) -> TalentMobileLinkPolicy:
        validated = _validate_ttl_days(ttl_days)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO workflow_notification_settings (
                        scope_key, talent_mobile_link_ttl_days, updated_by
                    ) VALUES (%s,%s,%s)
                    ON CONFLICT (scope_key) DO UPDATE SET
                        talent_mobile_link_ttl_days = EXCLUDED.talent_mobile_link_ttl_days,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    """,
                    (scope_key, validated, actor),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_talent_mobile_link_policy",
            ) from error
        return TalentMobileLinkPolicy(scope_key=scope_key, ttl_days=validated)
