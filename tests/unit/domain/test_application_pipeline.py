from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from digital_bast.application.ports import SyncCursor
from digital_bast.application.services import PipelineService
from digital_bast.domain.models import (
    DomainRecord,
    Employee,
    EmployeeId,
    EmployeeRole,
    EntityKind,
    Month,
    RecordKey,
    RecordOrigin,
)
from digital_bast.domain.scheduling import ProcedureName
from digital_bast.domain.timesheets import (
    TimesheetGeneration,
    TimesheetOptions,
    generate_monthly_timesheets,
)
from digital_bast.domain.transforms import (
    AttendanceInput,
    RedmineTaskInput,
    transform_attendance,
    transform_redmine_task,
)


class MemoryRecords:
    def __init__(self) -> None:
        self.values: dict[RecordKey, DomainRecord] = {}

    async def get(self, key: RecordKey) -> DomainRecord | None:
        return self.values.get(key)

    async def upsert(self, record: DomainRecord) -> None:
        self.values[record.key] = record

    async def list_month(
        self,
        kind: EntityKind,
        period: Month,
    ) -> tuple[DomainRecord, ...]:
        _ = kind, period
        return tuple(self.values.values())


class MemoryCursors:
    def __init__(self) -> None:
        self.values: dict[str, SyncCursor] = {}

    async def load(self, source: str) -> SyncCursor | None:
        return self.values.get(source)

    async def save(self, cursor: SyncCursor) -> None:
        self.values[cursor.source] = cursor


class ProcedureSpy:
    def __init__(self) -> None:
        self.calls: list[ProcedureName] = []

    async def execute(self, procedure: ProcedureName) -> None:
        self.calls.append(procedure)


@pytest.mark.asyncio
async def test_attendance_task_timesheet_replay_and_manual_lock() -> None:
    jakarta = ZoneInfo("Asia/Jakarta")
    employee = Employee(EmployeeId("17"), "NRP17", "Ani", EmployeeRole.DEVELOPER)
    attendance_input = AttendanceInput(
        employee.id,
        date(2026, 8, 3),
        datetime(2026, 8, 3, 8, tzinfo=jakarta),
        datetime(2026, 8, 3, 17, tzinfo=jakarta),
    )
    task_input = RedmineTaskInput(
        "991",
        employee.id,
        "Deploy API",
        "Product",
        "Closed",
        date(2026, 8, 3),
        date(2026, 8, 3),
        "DIGI-SI",
        100,
    )
    attendance = transform_attendance(attendance_input)
    task = transform_redmine_task(task_input)
    timesheets = generate_monthly_timesheets(
        TimesheetGeneration(
            (employee,),
            Month(2026, 8),
            (attendance,),
            (task,),
            (),
            (),
            TimesheetOptions("Development", "Weekend", "IoT", "PAMA"),
        )
    )
    records = MemoryRecords()
    service = PipelineService(records, MemoryCursors(), ProcedureSpy())

    first = await service.upsert((attendance, task, *timesheets))
    replay = await service.upsert((attendance, task, *timesheets))
    manual = replace(attendance, start_at=None, origin=RecordOrigin.MANUAL)
    records.values[attendance.key] = manual
    locked = await service.upsert((attendance,))

    assert first.created_or_updated == 33
    assert replay.unchanged == 33
    assert transform_attendance(attendance_input).key == attendance.key
    assert transform_redmine_task(task_input).key == task.key
    assert locked.locked == 1
    assert records.values[attendance.key] == manual
