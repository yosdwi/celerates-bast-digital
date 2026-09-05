"""Store-agnostic assembly of the per-employee facts the completion check needs.

The NocoDB-specific readers that used to live here are gone: since migration
20260820_0004 there is a single store (the typed tables in app Postgres) that
both the pipeline and NocoDB write, so there is nothing to read out of NocoDB's
own schema any more. The concrete readers now come from
infrastructure.local_completion_source and infrastructure.postgres_employees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final

from digital_bast.domain.completion import (
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

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.domain.completion import AttendanceFact, DateRange
    from digital_bast.domain.models import DomainRecord, Employee
    from digital_bast.infrastructure.production_sources import EmployeeSource

_MONTH_KINDS = (
    EntityKind.HOLIDAY,
    EntityKind.SCHEDULE,
    EntityKind.TIMESHEET,
    EntityKind.TASK,
)


class MonthlyRecordSource(Protocol):
    async def list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]: ...


class AttendanceReader(Protocol):
    async def load(self, period: DateRange) -> dict[tuple[str, date], AttendanceFact]: ...


class TaskEvidenceReader(Protocol):
    async def counts(self, period: DateRange) -> dict[str, int]: ...


@final
class CompletionSource:
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
                    {
                        record.work_date: record
                        for record in timesheets
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
