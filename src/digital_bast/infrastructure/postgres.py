from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, final

import psycopg
from psycopg.types.json import Jsonb

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from uuid import UUID

    from digital_bast.infrastructure.nocodb import JsonValue


@dataclass(frozen=True, slots=True)
class StoredRecord:
    source: str
    external_id: str
    entity_kind: str
    work_date: date
    payload: dict[str, JsonValue]
    source_updated_at: datetime | None
    version: int


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    plan_id: UUID
    owner_id: str
    status: str
    plan: dict[str, JsonValue]
    retention_until: datetime


@final
class PostgresStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn: str = dsn
        self._connect_timeout_seconds: int = connect_timeout_seconds

    def upsert_record(self, record: StoredRecord) -> int:
        statement = """
            INSERT INTO durable_records (
                source, external_id, entity_kind, work_date, payload, source_updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, external_id) DO UPDATE SET
                payload = EXCLUDED.payload,
                entity_kind = EXCLUDED.entity_kind,
                work_date = EXCLUDED.work_date,
                source_updated_at = EXCLUDED.source_updated_at,
                version = durable_records.version + 1,
                updated_at = now()
            WHERE durable_records.source_updated_at IS NULL
               OR EXCLUDED.source_updated_at IS NULL
               OR durable_records.source_updated_at <= EXCLUDED.source_updated_at
            RETURNING version
        """
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    statement,
                    (
                        record.source,
                        record.external_id,
                        record.entity_kind,
                        record.work_date,
                        Jsonb(record.payload),
                        record.source_updated_at,
                    ),
                )
                row = cursor.fetchone()
                return record.version if row is None else int(row[0])
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="upsert_record") from error

    def get_watermark(self, source_key: str) -> str | None:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    "SELECT cursor_value FROM sync_watermarks WHERE source_key = %s",
                    (source_key,),
                )
                row = cursor.fetchone()
                return None if row is None else str(row[0])
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="get_watermark") from error

    def set_watermark(self, source_key: str, cursor_value: str, watermark: datetime) -> None:
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
                    INSERT INTO sync_watermarks (source_key, cursor_value, watermark)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_key) DO UPDATE SET
                        cursor_value = EXCLUDED.cursor_value,
                        watermark = EXCLUDED.watermark,
                        updated_at = now()
                    """,
                    (source_key, cursor_value, watermark.astimezone(UTC)),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="set_watermark") from error

    def acquire_lock(self, record_key: str, owner_id: str, ttl_seconds: int) -> bool:
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
                    INSERT INTO manual_record_locks (record_key, owner_id, expires_at)
                    VALUES (%s, %s, now() + make_interval(secs => %s))
                    ON CONFLICT (record_key) DO UPDATE SET
                        owner_id = EXCLUDED.owner_id,
                        acquired_at = now(),
                        expires_at = EXCLUDED.expires_at
                    WHERE manual_record_locks.expires_at <= now()
                       OR manual_record_locks.owner_id = EXCLUDED.owner_id
                    RETURNING record_key
                    """,
                    (record_key, owner_id, ttl_seconds),
                )
                return cursor.fetchone() is not None
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="acquire_lock") from error

    def release_lock(self, record_key: str, owner_id: str) -> bool:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    "DELETE FROM manual_record_locks WHERE record_key = %s AND owner_id = %s",
                    (record_key, owner_id),
                )
                return cursor.rowcount == 1
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="release_lock") from error

    def save_generation_plan(self, plan: GenerationPlan) -> None:
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
                    INSERT INTO generation_plans (
                        id, owner_id, status, plan, retention_until
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        plan = EXCLUDED.plan,
                        retention_until = EXCLUDED.retention_until,
                        updated_at = now()
                    """,
                    (
                        plan.plan_id,
                        plan.owner_id,
                        plan.status,
                        Jsonb(plan.plan),
                        plan.retention_until.astimezone(UTC),
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_generation_plan",
            ) from error

    def purge_expired_plans(self, cutoff: datetime) -> int:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    "DELETE FROM generation_plans WHERE retention_until <= %s",
                    (cutoff.astimezone(UTC),),
                )
                return cursor.rowcount
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="purge_expired_plans",
            ) from error
