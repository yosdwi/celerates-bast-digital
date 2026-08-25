from __future__ import annotations

from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.talentops import SourceSyncSnapshot
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import datetime


class _SourceSyncRow:
    __slots__ = ("last_success_at", "source_key")

    def __init__(self, source_key: str, last_success_at: datetime) -> None:
        self.source_key = source_key
        self.last_success_at = last_success_at


@final
class PostgresSourceSyncStateStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def load(self) -> tuple[SourceSyncSnapshot, ...]:
        return await run_sync(self._load)

    async def record_success(self, source_key: str) -> None:
        await run_sync(self._record_success, source_key)

    def _load(self) -> tuple[SourceSyncSnapshot, ...]:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(_SourceSyncRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT source_key, last_success_at
                    FROM source_sync_state
                    ORDER BY source_key
                    """
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="load_source_sync_state",
            ) from error
        return tuple(
            SourceSyncSnapshot(
                source_key=row.source_key,
                last_success_at=row.last_success_at,
            )
            for row in rows
        )

    def _record_success(self, source_key: str) -> None:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    """
                    INSERT INTO source_sync_state (
                        source_key,
                        last_success_at,
                        updated_at
                    )
                    VALUES (%s, now(), now())
                    ON CONFLICT (source_key) DO UPDATE SET
                        last_success_at = EXCLUDED.last_success_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (source_key,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="record_source_sync_success",
            ) from error
