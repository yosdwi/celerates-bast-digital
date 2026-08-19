from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, final

import psycopg
from anyio.to_thread import run_sync
from psycopg import sql
from psycopg.rows import class_row
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from digital_bast.domain.completion import (
    AttendanceFact,
    EmployeeFacts,
    TaskFact,
    TimesheetFact,
    resolve_off_days,
)
from digital_bast.domain.identity import canonical_text
from digital_bast.domain.models import (
    EntityKind,
    Holiday,
    Month,
    Schedule,
    Task,
    Timesheet,
)
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from digital_bast.domain.completion import DateRange
    from digital_bast.domain.models import DomainRecord, Employee
    from digital_bast.infrastructure.production_sources import EmployeeSource


@dataclass(frozen=True, slots=True)
class _AttendanceRow:
    employee_id: object
    work_date: object
    clock_in: object
    clock_out: object
    evidence: object


@dataclass(frozen=True, slots=True)
class _EvidenceRow:
    id_key: object
    evidence: object


_EMPTY_MARKERS: Final = frozenset({"", "[]", "{}", "null", "none"})
_TASK_TABLES: Final = ("Tasklist IoT Operations", "Tasklist Developer")
_MONTH_KINDS: Final = (
    EntityKind.HOLIDAY,
    EntityKind.SCHEDULE,
    EntityKind.TIMESHEET,
    EntityKind.TASK,
)


class AttendanceMapping(BaseModel):
    """NocoDB attendance mapping; unresolved from code, supplied by NOCODB_ATTENDANCE_MAPPING."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    table: str = Field(min_length=1)
    date_column: str = Field(min_length=1)
    clock_in_column: str = Field(min_length=1)
    clock_out_column: str = Field(min_length=1)
    evidence_column: str = Field(min_length=1)
    employee_link_table: str = Field(min_length=1)
    employee_link_column: str = Field(min_length=1)


def parse_attendance_mapping(value: str | None) -> AttendanceMapping | None:
    if value is None or not value.strip():
        return None
    try:
        return AttendanceMapping.model_validate(json.loads(value))
    except (json.JSONDecodeError, ValidationError) as error:
        raise InfrastructureError(service="nocodb", operation="parse_attendance_mapping") from error


def has_value(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().casefold() not in _EMPTY_MARKERS


class MonthlyRecordSource(Protocol):
    async def list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]: ...


class AttendanceReader(Protocol):
    async def load(self, period: DateRange) -> dict[tuple[str, date], AttendanceFact]: ...


class TaskEvidenceReader(Protocol):
    async def counts(self, period: DateRange) -> dict[str, int]: ...


@final
class NocoDBAttendanceReader:
    def __init__(
        self,
        dsn: str,
        base_id: str,
        mapping: AttendanceMapping,
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._dsn: str = dsn
        self._base_id: str = base_id
        self._mapping: AttendanceMapping = mapping
        self._connect_timeout_seconds: int = connect_timeout_seconds

    async def load(self, period: DateRange) -> dict[tuple[str, date], AttendanceFact]:
        return await run_sync(self._load, period)

    def _statement(self) -> sql.Composed:
        mapping = self._mapping
        return sql.SQL(
            'SELECT link."Employee Data_id" AS employee_id, source.{work_date} AS work_date, '
            "source.{clock_in} AS clock_in, source.{clock_out} AS clock_out, "
            "source.{evidence} AS evidence "
            "FROM {schema}.{table} source "
            "LEFT JOIN {schema}.{link_table} link ON link.{link_column} = source.id "
            "WHERE source.{work_date} BETWEEN %s AND %s"
        ).format(
            schema=sql.Identifier(self._base_id),
            table=sql.Identifier(mapping.table),
            link_table=sql.Identifier(mapping.employee_link_table),
            link_column=sql.Identifier(mapping.employee_link_column),
            work_date=sql.Identifier(mapping.date_column),
            clock_in=sql.Identifier(mapping.clock_in_column),
            clock_out=sql.Identifier(mapping.clock_out_column),
            evidence=sql.Identifier(mapping.evidence_column),
        )

    def _load(self, period: DateRange) -> dict[tuple[str, date], AttendanceFact]:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(_AttendanceRow)) as cursor,
            ):
                _ = cursor.execute(self._statement(), (period.start, period.end))
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(service="nocodb", operation="list_attendance") from error
        return {
            (str(row.employee_id), work_date): AttendanceFact(
                work_date=work_date,
                has_clock_in=has_value(row.clock_in),
                has_clock_out=has_value(row.clock_out),
                has_evidence=has_value(row.evidence),
            )
            for row in rows
            if isinstance(work_date := row.work_date, date) and row.employee_id is not None
        }


@final
class NocoDBTaskEvidenceReader:
    def __init__(
        self,
        dsn: str,
        base_id: str,
        evidence_column: str,
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._dsn: str = dsn
        self._base_id: str = base_id
        self._evidence_column: str = evidence_column
        self._connect_timeout_seconds: int = connect_timeout_seconds

    async def counts(self, period: DateRange) -> dict[str, int]:
        return await run_sync(self._counts, period)

    def _counts(self, period: DateRange) -> dict[str, int]:
        # NocoDB has no column that maps its row Id_Key to the domain RecordKey
        # computed in domain/identity.py::task_key -- that correspondence was
        # never established anywhere in this codebase. Keying by Id_Key here is
        # therefore a best-effort placeholder: it is internally consistent with
        # the per-task-key TaskEvidenceReader protocol but won't line up with
        # real Task records. Harmless in practice -- NocoDB is unreachable and
        # this reader is never wired into create_run_context / operations.py.
        totals: dict[str, int] = {}
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(_EvidenceRow)) as cursor,
            ):
                for table in _TASK_TABLES:
                    statement = sql.SQL(
                        'SELECT "Id_Key" AS id_key, {evidence} AS evidence '
                        "FROM {schema}.{table} "
                        'WHERE "Date" BETWEEN %s AND %s'
                    ).format(
                        schema=sql.Identifier(self._base_id),
                        table=sql.Identifier(table),
                        evidence=sql.Identifier(self._evidence_column),
                    )
                    _ = cursor.execute(statement, (period.start, period.end))
                    for row in cursor.fetchall():
                        if not has_value(row.evidence):
                            continue
                        key = str(row.id_key or "")
                        if key:
                            totals[key] = totals.get(key, 0) + 1
        except psycopg.Error as error:
            raise InfrastructureError(service="nocodb", operation="list_task_evidence") from error
        return totals


@final
class NocoDBCompletionSource:
    def __init__(
        self,
        employees: EmployeeSource,
        records: MonthlyRecordSource,
        attendance: AttendanceReader | None = None,
        evidence: TaskEvidenceReader | None = None,
    ) -> None:
        self._employees = employees
        self._records = records
        self._attendance = attendance
        self._evidence = evidence

    async def load(
        self,
        period: DateRange,
        employee: str | None = None,
    ) -> tuple[EmployeeFacts, ...]:
        selected = _select_employees(await self._employees.load(), employee)
        holidays, schedules, timesheets, tasks = await self._load_period(period)
        attendance = await self._attendance.load(period) if self._attendance is not None else {}
        evidence = await self._evidence.counts(period) if self._evidence is not None else {}
        holiday_by_day = {record.work_date: record for record in holidays}
        return tuple(
            EmployeeFacts(
                employee_id=str(person.id),
                name=person.name,
                off_days=resolve_off_days(
                    person.role,
                    period,
                    holiday_by_day,
                    {
                        record.work_date: record
                        for record in schedules
                        if record.employee_id == person.id
                    },
                ),
                attendance=tuple(
                    fact
                    for (employee_id, _day), fact in sorted(attendance.items())
                    if employee_id == str(person.id)
                ),
                timesheets=tuple(
                    TimesheetFact(record.work_date, record.remarks)
                    for record in timesheets
                    if record.employee_id == person.id
                ),
                tasks=tuple(
                    TaskFact(
                        record.work_date,
                        record.title,
                        record.status,
                        evidence.get(str(record.key), 0),
                    )
                    for record in tasks
                    if record.employee_id == person.id
                ),
                evidence_available=self._evidence is not None,
                attendance_available=self._attendance is not None,
            )
            for person in selected
        )

    async def _load_period(
        self,
        period: DateRange,
    ) -> tuple[
        tuple[Holiday, ...],
        tuple[Schedule, ...],
        tuple[Timesheet, ...],
        tuple[Task, ...],
    ]:
        holidays: list[Holiday] = []
        schedules: list[Schedule] = []
        timesheets: list[Timesheet] = []
        tasks: list[Task] = []
        for year, month in period.months():
            for kind in _MONTH_KINDS:
                for record in await self._records.list_month(kind, Month(year, month)):
                    if not period.start <= record.work_date <= period.end:
                        continue
                    match record:
                        case Holiday():
                            holidays.append(record)
                        case Schedule():
                            schedules.append(record)
                        case Timesheet():
                            timesheets.append(record)
                        case Task():
                            tasks.append(record)
                        case _:
                            continue
        return tuple(holidays), tuple(schedules), tuple(timesheets), tuple(tasks)


def _select_employees(
    employees: tuple[Employee, ...],
    employee: str | None,
) -> tuple[Employee, ...]:
    ordered = sorted(employees, key=lambda item: (item.name, str(item.id)))
    if employee is None or not employee.strip():
        return tuple(ordered)
    needle = canonical_text(employee)
    return tuple(person for person in ordered if needle in canonical_text(person.name))
