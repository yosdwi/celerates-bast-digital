from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final

from digital_bast.domain.models import (
    Attendance,
    Employee,
    EntityKind,
    Holiday,
    Month,
    Schedule,
    Task,
    Timesheet,
)
from digital_bast.domain.reference import generate_iot_schedules
from digital_bast.domain.timesheets import (
    TimesheetGeneration,
    TimesheetOptions,
    generate_monthly_timesheets,
)
from digital_bast.domain.transforms import IoTTaskInput, transform_iot_task
from digital_bast.flows.models import Operation, Period, StepSummary

if TYPE_CHECKING:
    from digital_bast.application.services import BatchResult
    from digital_bast.domain.models import DomainRecord


class EmployeeSource(Protocol):
    async def load(self) -> tuple[Employee, ...]: ...


class IoTTaskSource(Protocol):
    async def load(
        self,
        period: Period,
        employees: tuple[Employee, ...],
    ) -> tuple[IoTTaskInput, ...]: ...


class RecordUpserter(Protocol):
    async def upsert(self, records: tuple[DomainRecord, ...]) -> BatchResult: ...


class MonthlyRecordSource(Protocol):
    async def list_month(
        self,
        kind: EntityKind,
        period: Month,
    ) -> tuple[DomainRecord, ...]: ...


class IoTPicUpdater(Protocol):
    async def update(self) -> int: ...


_GENERATION_KINDS: tuple[EntityKind, ...] = (
    EntityKind.HOLIDAY,
    EntityKind.ATTENDANCE,
    EntityKind.TASK,
    EntityKind.SCHEDULE,
)
_DURABLE_KINDS: tuple[EntityKind, ...] = tuple(EntityKind)


async def _load_records(
    source: MonthlyRecordSource,
    period: Month,
    kinds: tuple[EntityKind, ...],
) -> tuple[DomainRecord, ...]:
    records: list[DomainRecord] = []
    for kind in kinds:
        records.extend(await source.list_month(kind, period))
    return tuple(records)


def _partition_records(
    records: tuple[DomainRecord, ...],
) -> tuple[
    tuple[Attendance, ...],
    tuple[Task, ...],
    tuple[Holiday, ...],
    tuple[Schedule, ...],
]:
    attendance: list[Attendance] = []
    tasks: list[Task] = []
    holidays: list[Holiday] = []
    schedules: list[Schedule] = []
    for record in records:
        match record:
            case Attendance():
                attendance.append(record)
            case Task():
                tasks.append(record)
            case Holiday():
                holidays.append(record)
            case Schedule():
                schedules.append(record)
            case Timesheet():
                pass
    return tuple(attendance), tuple(tasks), tuple(holidays), tuple(schedules)


@final
class IoTTaskImportOperation:
    def __init__(
        self,
        employees: EmployeeSource,
        source: IoTTaskSource,
        records: RecordUpserter,
    ) -> None:
        self._employees = employees
        self._source = source
        self._records = records

    async def execute(self, period: Period) -> StepSummary:
        employee_rows = await self._employees.load()
        source_rows = await self._source.load(period, employee_rows)
        tasks = tuple(transform_iot_task(row) for row in source_rows)
        result = await self._records.upsert(tasks)
        return StepSummary(
            operation=Operation.IOT_TASK_IMPORT,
            read=len(source_rows),
            written=result.created_or_updated,
            unchanged=result.unchanged,
            locked=result.locked,
        )


@final
class ScheduleSyncOperation:
    def __init__(self, employees: EmployeeSource, records: RecordUpserter) -> None:
        self._employees = employees
        self._records = records

    async def execute(self, period: Period) -> StepSummary:
        employee_rows = await self._employees.load()
        schedules = generate_iot_schedules(employee_rows, Month(period.year, period.month))
        result = await self._records.upsert(schedules)
        return StepSummary(
            operation=Operation.SCHEDULE_SYNC,
            read=len(employee_rows),
            written=result.created_or_updated,
            unchanged=result.unchanged,
            locked=result.locked,
        )


@final
class TimesheetGenerationOperation:
    def __init__(
        self,
        employees: EmployeeSource,
        monthly: MonthlyRecordSource,
        records: RecordUpserter,
        options: TimesheetOptions,
    ) -> None:
        self._employees = employees
        self._monthly = monthly
        self._records = records
        self._options = options

    async def execute(self, period: Period) -> StepSummary:
        employee_rows = await self._employees.load()
        month = Month(period.year, period.month)
        monthly_records = await _load_records(self._monthly, month, _GENERATION_KINDS)
        attendance, tasks, holidays, schedules = _partition_records(monthly_records)
        timesheets = generate_monthly_timesheets(
            TimesheetGeneration(
                employee_rows,
                month,
                attendance,
                tasks,
                holidays,
                schedules,
                self._options,
            )
        )
        result = await self._records.upsert(timesheets)
        return StepSummary(
            operation=Operation.TIMESHEET_GENERATION,
            read=len(employee_rows) + len(monthly_records),
            written=result.created_or_updated,
            unchanged=result.unchanged,
            locked=result.locked,
        )


@final
class ReconciliationOperation:
    def __init__(self, monthly: MonthlyRecordSource) -> None:
        self._monthly = monthly

    async def execute(self, period: Period) -> StepSummary:
        records = await _load_records(
            self._monthly,
            Month(period.year, period.month),
            _DURABLE_KINDS,
        )
        count = len(records)
        return StepSummary(
            operation=Operation.RECONCILIATION,
            read=count,
            written=0,
            unchanged=count,
        )


@final
class IoTPicUpdateOperation:
    def __init__(self, updater: IoTPicUpdater) -> None:
        self._updater = updater

    async def execute(self, period: Period) -> StepSummary:
        del period
        inserted = await self._updater.update()
        return StepSummary(operation=Operation.IOT_PIC_UPDATE, read=0, written=inserted)
