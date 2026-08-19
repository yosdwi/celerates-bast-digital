from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, assert_never, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter, ValidationError

from digital_bast.application.ports import SyncCursor
from digital_bast.domain.errors import CursorRegressionError
from digital_bast.domain.models import (
    Attendance,
    DomainRecord,
    EntityKind,
    Holiday,
    Month,
    RecordKey,
    Schedule,
    Task,
    Timesheet,
)
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.infrastructure.repository_models import (
    DOMAIN_RECORD_ADAPTER,
    CursorRow,
    DomainRecordRow,
    PayloadRow,
)

if TYPE_CHECKING:
    from digital_bast.domain.scheduling import ProcedureName
    from digital_bast.infrastructure.healthcheck import PostgresHealthcheck
    from digital_bast.infrastructure.nocodb import JsonValue

_HOLIDAY = TypeAdapter(Holiday)
_ATTENDANCE = TypeAdapter(Attendance)
_TASK = TypeAdapter(Task)
_SCHEDULE = TypeAdapter(Schedule)
_TIMESHEET = TypeAdapter(Timesheet)
_PROCEDURE_PART_COUNT = 2


def _entity_kind(record: DomainRecord) -> EntityKind:
    match record:
        case Holiday():
            return EntityKind.HOLIDAY
        case Attendance():
            return EntityKind.ATTENDANCE
        case Task():
            return EntityKind.TASK
        case Schedule():
            return EntityKind.SCHEDULE
        case Timesheet():
            return EntityKind.TIMESHEET
        case _:
            assert_never(record)


def _parse_record(kind: EntityKind, payload: dict[str, JsonValue]) -> DomainRecord:
    try:
        match kind:
            case EntityKind.HOLIDAY:
                return _HOLIDAY.validate_python(payload)
            case EntityKind.ATTENDANCE:
                return _ATTENDANCE.validate_python(payload)
            case EntityKind.TASK:
                return _TASK.validate_python(payload)
            case EntityKind.SCHEDULE:
                return _SCHEDULE.validate_python(payload)
            case EntityKind.TIMESHEET:
                return _TIMESHEET.validate_python(payload)
            case _:
                assert_never(kind)
    except ValidationError as error:
        raise InfrastructureError(service="postgres", operation="parse_domain_record") from error


@final
class PostgresDomainRepository:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn: str = dsn
        self._connect_timeout_seconds: int = connect_timeout_seconds

    async def get(self, key: RecordKey) -> DomainRecord | None:
        return await run_sync(self._get, key)

    async def upsert(self, record: DomainRecord) -> None:
        await run_sync(self._upsert, record)

    async def list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]:
        return await run_sync(self._list_month, kind, period)

    def _get(self, key: RecordKey) -> DomainRecord | None:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(DomainRecordRow)) as cursor,
            ):
                _ = cursor.execute(
                    "SELECT entity_kind, payload FROM durable_records"
                    " WHERE source = 'domain' AND external_id = %s",
                    (str(key),),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            return _parse_record(row.entity_kind, row.payload)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="get_domain_record") from error

    def _upsert(self, record: DomainRecord) -> None:
        kind = _entity_kind(record)
        payload = DOMAIN_RECORD_ADAPTER.dump_python(record, mode="json")
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
                    INSERT INTO durable_records (
                        source, external_id, entity_kind, work_date, payload
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source, external_id) DO UPDATE SET
                        entity_kind = EXCLUDED.entity_kind,
                        work_date = EXCLUDED.work_date,
                        payload = EXCLUDED.payload,
                        version = durable_records.version + 1,
                        updated_at = now()
                    WHERE durable_records.payload->>'origin' <> 'manual'
                    """,
                    ("domain", str(record.key), kind.value, record.work_date, Jsonb(payload)),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="upsert_domain_record",
            ) from error

    def _list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(PayloadRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT payload FROM durable_records
                    WHERE source = 'domain'
                      AND entity_kind = %s
                      AND work_date >= make_date(%s, %s, 1)
                      AND work_date < make_date(%s, %s, 1) + interval '1 month'
                    ORDER BY work_date, external_id
                    """,
                    (kind.value, period.year, period.month, period.year, period.month),
                )
                rows = cursor.fetchall()
            return tuple(_parse_record(kind, row.payload) for row in rows)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="list_month") from error


@final
class PostgresCursorStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn: str = dsn
        self._connect_timeout_seconds: int = connect_timeout_seconds

    async def load(self, source: str) -> SyncCursor | None:
        return await run_sync(self._load, source)

    async def save(self, cursor: SyncCursor) -> None:
        await run_sync(self._save, cursor)

    def _load(self, source: str) -> SyncCursor | None:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(CursorRow)) as db_cursor,
            ):
                _ = db_cursor.execute(
                    "SELECT cursor_value, watermark FROM sync_watermarks WHERE source_key = %s",
                    (source,),
                )
                row = db_cursor.fetchone()
            return None if row is None else SyncCursor(source, row.cursor_value, row.watermark)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="load_cursor") from error

    def _save(self, cursor: SyncCursor) -> None:
        watermark = cursor.watermark.astimezone(UTC)
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as db_cursor,
            ):
                _ = db_cursor.execute(
                    """
                    INSERT INTO sync_watermarks (source_key, cursor_value, watermark)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_key) DO UPDATE SET
                        cursor_value = EXCLUDED.cursor_value,
                        watermark = EXCLUDED.watermark,
                        updated_at = now()
                    WHERE sync_watermarks.watermark <= EXCLUDED.watermark
                    RETURNING source_key
                    """,
                    (cursor.source, cursor.token, watermark),
                )
                saved = db_cursor.fetchone() is not None
            if not saved:
                raise CursorRegressionError(cursor.source)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="save_cursor") from error


@final
class PostgresStoredProcedureAdapter:
    def __init__(self, healthcheck: PostgresHealthcheck) -> None:
        self._healthcheck: PostgresHealthcheck = healthcheck

    async def execute(self, procedure: ProcedureName) -> None:
        parts = str(procedure).split(".")
        if len(parts) != _PROCEDURE_PART_COUNT:
            raise InfrastructureError(service="postgres", operation="parse_procedure_name")
        await run_sync(self._healthcheck.call_procedure, parts[0], parts[1])
