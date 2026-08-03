from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from digital_bast.application.services import BatchResult
from digital_bast.domain.models import (
    Employee,
    EmployeeId,
    EmployeeRole,
    EntityKind,
    Month,
)
from digital_bast.domain.reference import HolidayInput, transform_holiday
from digital_bast.domain.timesheets import TimesheetOptions
from digital_bast.domain.transforms import IoTTaskInput
from digital_bast.flows.models import Operation, Period
from digital_bast.flows.production_operations import (
    IoTPicUpdateOperation,
    IoTTaskImportOperation,
    ReconciliationOperation,
    ScheduleSyncOperation,
    TimesheetGenerationOperation,
)

if TYPE_CHECKING:
    from digital_bast.domain.models import DomainRecord


class EmployeeSourceFake:
    async def load(self) -> tuple[Employee, ...]:
        return (
            Employee(EmployeeId("7"), "IOT-7", "Operator One", EmployeeRole.IOT_OPERATIONS),
            Employee(EmployeeId("8"), "DEV-8", "Developer One", EmployeeRole.DEVELOPER),
        )


class IoTTaskSourceFake:
    async def load(
        self,
        period: Period,
        _employees: tuple[Employee, ...],
    ) -> tuple[IoTTaskInput, ...]:
        return (
            IoTTaskInput(
                source_id="2026-08-03:7:sensor-offline",
                employee_id=EmployeeId("7"),
                issue="Sensor offline",
                issue_type="Alert",
                work_date=date(period.year, period.month, 3),
                first_responder="Operator One",
                start_at=None,
                response_at=None,
                close_at=None,
            ),
        )


class RecordUpserterSpy:
    def __init__(self) -> None:
        self.records: tuple[DomainRecord, ...] = ()

    async def upsert(self, records: tuple[DomainRecord, ...]) -> BatchResult:
        self.records = records
        return BatchResult(len(records), 0, 0)


class MonthlyRecordSourceFake:
    def __init__(self) -> None:
        self.holiday = transform_holiday(HolidayInput(date(2026, 8, 17), "Independence Day"))

    async def list_month(
        self,
        kind: EntityKind,
        _period: Month,
    ) -> tuple[DomainRecord, ...]:
        return (self.holiday,) if kind is EntityKind.HOLIDAY else ()


class IoTPicUpdaterFake:
    async def update(self) -> int:
        return 3


@pytest.mark.asyncio
async def test_iot_import_transforms_sheet_rows_and_upserts_tasks() -> None:
    records = RecordUpserterSpy()
    operation = IoTTaskImportOperation(EmployeeSourceFake(), IoTTaskSourceFake(), records)

    summary = await operation.execute(Period.parse("2026-08"))

    assert summary.operation is Operation.IOT_TASK_IMPORT
    assert summary.read == 1
    assert summary.written == 1
    assert str(records.records[0].key).startswith("task:2026-08-03:7:")


@pytest.mark.asyncio
async def test_schedule_sync_generates_every_day_for_iot_employees_only() -> None:
    records = RecordUpserterSpy()
    operation = ScheduleSyncOperation(EmployeeSourceFake(), records)

    summary = await operation.execute(Period.parse("2026-08"))

    assert summary.operation is Operation.SCHEDULE_SYNC
    assert summary.read == 2
    assert summary.written == 31
    assert len(records.records) == 31


@pytest.mark.asyncio
async def test_timesheet_generation_builds_every_employee_day_from_monthly_records() -> None:
    records = RecordUpserterSpy()
    operation = TimesheetGenerationOperation(
        EmployeeSourceFake(),
        MonthlyRecordSourceFake(),
        records,
        TimesheetOptions("Weekday", "Weekend", "IoT", "PAMA"),
    )

    summary = await operation.execute(Period.parse("2026-08"))

    assert summary.operation is Operation.TIMESHEET_GENERATION
    assert summary.read == 3
    assert summary.written == 62
    assert len(records.records) == 62


@pytest.mark.asyncio
async def test_reconciliation_reads_every_durable_kind_without_rewriting_valid_rows() -> None:
    source = MonthlyRecordSourceFake()
    operation = ReconciliationOperation(source)

    summary = await operation.execute(Period.parse("2026-08"))

    assert summary.operation is Operation.RECONCILIATION
    assert summary.read == 1
    assert summary.written == 0
    assert summary.unchanged == 1


@pytest.mark.asyncio
async def test_iot_pic_update_reports_inserted_employee_links() -> None:
    operation = IoTPicUpdateOperation(IoTPicUpdaterFake())

    summary = await operation.execute(Period.parse("2026-08"))

    assert summary.operation is Operation.IOT_PIC_UPDATE
    assert summary.written == 3
