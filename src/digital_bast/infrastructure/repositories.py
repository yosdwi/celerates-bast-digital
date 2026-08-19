"""Domain repository over the typed business tables.

Replaces the durable_records jsonb blob (see migration 20260820_0004). Each
entity kind has its own table with a surrogate `id` primary key so NocoDB can
edit the same rows the pipeline writes -- one store, no sync.

`record_key` carries the RecordKey strings from domain/identity.py unchanged,
so identity semantics are exactly what they were.

Manual-edit protection is now a database trigger (`mark_manual_edit`) plus the
`WHERE origin <> 'manual'` guard on every upsert, replacing the old
`payload->>'origin' <> 'manual'` test. `version` and `updated_at` are owned by
the trigger, so no upsert touches them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, LiteralString, assert_never, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row, dict_row

from digital_bast.application.ports import SyncCursor
from digital_bast.domain.errors import CursorRegressionError
from digital_bast.domain.models import (
    Attendance,
    DomainRecord,
    EmployeeId,
    EntityKind,
    Holiday,
    Month,
    RecordKey,
    RecordOrigin,
    Schedule,
    Task,
    TaskCategory,
    TaskSource,
    Timesheet,
)
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.infrastructure.repository_models import CursorRow

if TYPE_CHECKING:
    from datetime import date, time

    from digital_bast.domain.scheduling import ProcedureName
    from digital_bast.infrastructure.healthcheck import PostgresHealthcheck

_PROCEDURE_PART_COUNT = 2

_SELECT: dict[EntityKind, LiteralString] = {
    EntityKind.HOLIDAY: "SELECT record_key, work_date, name, origin FROM holidays",
    EntityKind.ATTENDANCE: (
        "SELECT record_key, employee_id, work_date, check_in, check_out, origin FROM attendance"
    ),
    EntityKind.TASK: (
        "SELECT record_key, employee_id, work_date, title, requestor, status,"
        " category, task_source, source_id, assignee, start_at, response_at,"
        " close_at, end_date, achievement, issue_type, origin FROM tasks"
    ),
    EntityKind.SCHEDULE: (
        "SELECT record_key, employee_id, work_date, shift_name, origin FROM schedules"
    ),
    EntityKind.TIMESHEET: (
        "SELECT record_key, employee_id, work_date, calendar_month, activity,"
        " project, is_holiday, remarks, origin FROM timesheets"
    ),
}


_BY_KEY_SUFFIX: Final = " WHERE record_key = %s"
_MONTH_SUFFIX: Final = (
    " WHERE work_date >= make_date(%s, %s, 1)"
    "   AND work_date < make_date(%s, %s, 1) + interval '1 month'"
    " ORDER BY work_date, record_key"
)
# Built once so psycopg receives LiteralString rather than a runtime f-string.
_SELECT_BY_KEY: dict[EntityKind, LiteralString] = {
    kind: statement + _BY_KEY_SUFFIX for kind, statement in _SELECT.items()
}
_SELECT_MONTH: dict[EntityKind, LiteralString] = {
    kind: statement + _MONTH_SUFFIX for kind, statement in _SELECT.items()
}


def _kind_of_key(key: RecordKey) -> EntityKind | None:
    """RecordKey values are `<kind>:<...>` (domain/identity.py), so the prefix
    names the table to look in without probing all five.
    """
    prefix = str(key).split(":", 1)[0]
    try:
        return EntityKind(prefix)
    except ValueError:
        return None


def _clock(work_date: date, value: time | None) -> datetime | None:
    return None if value is None else datetime.combine(work_date, value, JAKARTA)


def _upsert_statement(record: DomainRecord) -> tuple[LiteralString, tuple[Any, ...]]:
    match record:
        case Holiday():
            return (
                """
                INSERT INTO holidays (record_key, work_date, name, origin)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    work_date = EXCLUDED.work_date,
                    name = EXCLUDED.name
                WHERE holidays.origin <> 'manual'
                """,
                (str(record.key), record.work_date, record.name, record.origin.value),
            )
        case Attendance():
            return (
                """
                INSERT INTO attendance (
                    record_key, employee_id, work_date, check_in, check_out, origin
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    work_date = EXCLUDED.work_date,
                    check_in = EXCLUDED.check_in,
                    check_out = EXCLUDED.check_out
                WHERE attendance.origin <> 'manual'
                """,
                (
                    str(record.key),
                    str(record.employee_id),
                    record.work_date,
                    record.start_at.timetz() if record.start_at is not None else None,
                    record.end_at.timetz() if record.end_at is not None else None,
                    record.origin.value,
                ),
            )
        case Task():
            return (
                """
                INSERT INTO tasks (
                    record_key, employee_id, work_date, title, requestor, status,
                    category, task_source, source_id, assignee, start_at,
                    response_at, close_at, end_date, achievement, issue_type, origin
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    work_date = EXCLUDED.work_date,
                    title = EXCLUDED.title,
                    requestor = EXCLUDED.requestor,
                    status = EXCLUDED.status,
                    category = EXCLUDED.category,
                    task_source = EXCLUDED.task_source,
                    source_id = EXCLUDED.source_id,
                    assignee = EXCLUDED.assignee,
                    start_at = EXCLUDED.start_at,
                    response_at = EXCLUDED.response_at,
                    close_at = EXCLUDED.close_at,
                    end_date = EXCLUDED.end_date,
                    achievement = EXCLUDED.achievement,
                    issue_type = EXCLUDED.issue_type
                WHERE tasks.origin <> 'manual'
                """,
                (
                    str(record.key),
                    str(record.employee_id),
                    record.work_date,
                    record.title,
                    record.requestor,
                    record.status,
                    record.category.value,
                    record.source.value,
                    record.source_id,
                    record.assignee or "",
                    record.start_at,
                    record.response_at,
                    record.close_at,
                    record.end_date,
                    record.achievement,
                    record.issue_type or "",
                    record.origin.value,
                ),
            )
        case Schedule():
            return (
                """
                INSERT INTO schedules (
                    record_key, employee_id, work_date, shift_name, origin
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    work_date = EXCLUDED.work_date,
                    shift_name = EXCLUDED.shift_name
                WHERE schedules.origin <> 'manual'
                """,
                (
                    str(record.key),
                    str(record.employee_id),
                    record.work_date,
                    record.shift_name or "",
                    record.origin.value,
                ),
            )
        case Timesheet():
            # attendance_key/task_keys are intentionally not persisted: nothing
            # reads them back (the NocoDB repository dropped them too), and
            # storing them would reintroduce the key-string sprawl the typed
            # tables exist to remove.
            return (
                """
                INSERT INTO timesheets (
                    record_key, employee_id, work_date, calendar_month, activity,
                    project, is_holiday, remarks, origin
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    work_date = EXCLUDED.work_date,
                    calendar_month = EXCLUDED.calendar_month,
                    activity = EXCLUDED.activity,
                    project = EXCLUDED.project,
                    is_holiday = EXCLUDED.is_holiday,
                    remarks = EXCLUDED.remarks
                WHERE timesheets.origin <> 'manual'
                """,
                (
                    str(record.key),
                    str(record.employee_id),
                    record.work_date,
                    record.calendar_month,
                    record.activity,
                    record.project,
                    record.is_holiday,
                    record.remarks,
                    record.origin.value,
                ),
            )
        case _:
            assert_never(record)


def _row_to_record(kind: EntityKind, row: dict[str, Any]) -> DomainRecord:
    origin = RecordOrigin(row["origin"])
    key = RecordKey(row["record_key"])
    match kind:
        case EntityKind.HOLIDAY:
            return Holiday(key, row["work_date"], row["name"], origin)
        case EntityKind.ATTENDANCE:
            work_date = row["work_date"]
            return Attendance(
                key,
                EmployeeId(row["employee_id"]),
                work_date,
                _clock(work_date, row["check_in"]),
                _clock(work_date, row["check_out"]),
                origin,
            )
        case EntityKind.TASK:
            return Task(
                key,
                EmployeeId(row["employee_id"]),
                row["work_date"],
                row["title"],
                row["requestor"],
                row["status"],
                TaskCategory(row["category"]),
                TaskSource(row["task_source"]),
                row["source_id"],
                row["assignee"] or None,
                row["start_at"],
                row["response_at"],
                row["close_at"],
                row["end_date"],
                row["achievement"],
                origin,
                row["issue_type"] or None,
            )
        case EntityKind.SCHEDULE:
            return Schedule(
                key,
                EmployeeId(row["employee_id"]),
                row["work_date"],
                row["shift_name"] or None,
                origin,
            )
        case EntityKind.TIMESHEET:
            return Timesheet(
                key,
                EmployeeId(row["employee_id"]),
                row["work_date"],
                row["calendar_month"],
                row["activity"],
                row["project"],
                row["is_holiday"],
                row["remarks"],
                None,
                (),
                origin,
            )
        case _:
            assert_never(kind)


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
        kind = _kind_of_key(key)
        if kind is None:
            return None
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(_SELECT_BY_KEY[kind], (str(key),))
                row = cursor.fetchone()
            return None if row is None else _row_to_record(kind, row)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="get_domain_record") from error

    def _upsert(self, record: DomainRecord) -> None:
        statement, parameters = _upsert_statement(record)
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(statement, parameters)
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
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    _SELECT_MONTH[kind],
                    (period.year, period.month, period.year, period.month),
                )
                rows = cursor.fetchall()
            return tuple(_row_to_record(kind, row) for row in rows)
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
