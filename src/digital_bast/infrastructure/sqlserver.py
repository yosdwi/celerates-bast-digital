from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol, final

import pyodbc
from anyio.to_thread import run_sync

from digital_bast.application.ports import SourceBatch, SourceWindow, SyncCursor
from digital_bast.infrastructure.errors import InfrastructureError, UpstreamTimeoutError

type SqlValue = str | int | float | bool | date | datetime | None
type SqlRow = dict[str, SqlValue]


class Cursor(Protocol):
    @property
    def description(self) -> Sequence[Sequence[SqlValue]]: ...

    def execute(self, statement: str, *parameters: SqlValue) -> Cursor: ...

    def fetchall(self) -> Sequence[Sequence[SqlValue]]: ...

    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], Connection]


ATTENDANCE_QUERY = """
WITH data_raw AS (
    SELECT h.attendance_date, h.attendance_hour, h.trans, h.nrp, u.name, h.dstrct_code
    FROM db_attendance.attend.tbl_t_att_daily_history h
    LEFT JOIN db_pamamobile.dbo.tbl_user u ON u.nrp = h.nrp
    WHERE h.nrp = ? AND h.attendance_date BETWEEN ? AND ? AND u.is_pama = 0 AND u.active = 1
    UNION ALL
    SELECT d.attendance_date, d.attendance_hour, d.trans, d.nrp, u.name, d.dstrct_code
    FROM db_attendance.attend.tbl_t_att_daily d
    LEFT JOIN db_pamamobile.dbo.tbl_user u ON u.nrp = d.nrp
    WHERE d.nrp = ? AND d.attendance_date BETWEEN ? AND ? AND u.is_pama = 0 AND u.active = 1
)
SELECT attendance_date, attendance_hour, trans, nrp, name, dstrct_code
FROM data_raw ORDER BY attendance_date, attendance_hour
"""

REDMINE_QUERY = """
SELECT login, nrp, nama, project_id, project_name, tracker_id, tracker_name,
       isu_id, isu_subject, description, start_date, due_date, created_on,
       closed_on, status_id, status_desc, author_id, author_name, done_ratio,
       estimated_hours, parent_id, updated_on
FROM DB_SATUPAMA_CIS.dbo.cis_jiep_tbl_redmine_bigdata_all_wi_digi
WHERE (start_date >= ? AND start_date <= ?) OR (created_on >= ? AND created_on <= ?)
ORDER BY start_date DESC, created_on DESC
"""


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date


@final
class SqlServerSource:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory: ConnectionFactory = connection_factory

    def attendance(self, employee_number: str, period: DateRange) -> list[SqlRow]:
        parameters: tuple[SqlValue, ...] = (
            employee_number,
            period.start,
            period.end,
            employee_number,
            period.start,
            period.end,
        )
        return self._query(ATTENDANCE_QUERY, parameters, "attendance")

    def redmine_tasks(self, period: DateRange) -> list[SqlRow]:
        parameters: tuple[SqlValue, ...] = (
            period.start,
            period.end,
            period.start,
            period.end,
        )
        return self._query(REDMINE_QUERY, parameters, "redmine_tasks")

    def _query(
        self,
        statement: str,
        parameters: tuple[SqlValue, ...],
        operation: str,
    ) -> list[SqlRow]:
        try:
            with managed_connection(self._connection_factory) as connection:
                cursor = connection.cursor()
                try:
                    _ = cursor.execute(statement, *parameters)
                    columns = [str(column[0]) for column in cursor.description]
                    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
                finally:
                    cursor.close()
        except pyodbc.OperationalError as error:
            if "timeout" in str(error).casefold():
                raise UpstreamTimeoutError(service="sqlserver", operation=operation) from error
            raise InfrastructureError(service="sqlserver", operation=operation) from error
        except pyodbc.Error as error:
            raise InfrastructureError(service="sqlserver", operation=operation) from error


@contextmanager
def managed_connection(factory: ConnectionFactory) -> Generator[Connection]:
    connection = factory()
    try:
        yield connection
    finally:
        connection.close()


def connection_factory(connection_string: str, timeout_seconds: int = 5) -> ConnectionFactory:
    def connect() -> Connection:
        return pyodbc.connect(connection_string, timeout=timeout_seconds)

    return connect


@final
class SqlServerAttendanceSource:
    def __init__(self, source: SqlServerSource, employee_number: str) -> None:
        self._source: SqlServerSource = source
        self._employee_number: str = employee_number

    async def fetch(
        self,
        window: SourceWindow,
        cursor: SyncCursor | None,
    ) -> SourceBatch[SqlRow]:
        start = window.start
        if cursor is not None and cursor.watermark > start:
            start = cursor.watermark
        period = DateRange(start.date(), window.end.date())
        rows = await run_sync(
            self._source.attendance,
            self._employee_number,
            period,
        )
        watermark = window.end.astimezone(UTC)
        return SourceBatch(
            tuple(rows),
            SyncCursor("sqlserver_attendance", watermark.isoformat(), watermark),
        )


@final
class SqlServerRedmineSource:
    def __init__(self, source: SqlServerSource) -> None:
        self._source: SqlServerSource = source

    async def fetch(
        self,
        window: SourceWindow,
        cursor: SyncCursor | None,
    ) -> SourceBatch[SqlRow]:
        start = window.start
        if cursor is not None and cursor.watermark > start:
            start = cursor.watermark
        period = DateRange(start.date(), window.end.date())
        rows = await run_sync(self._source.redmine_tasks, period)
        watermark = window.end.astimezone(UTC)
        return SourceBatch(
            tuple(rows),
            SyncCursor("sqlserver_redmine", watermark.isoformat(), watermark),
        )
