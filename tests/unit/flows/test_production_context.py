from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

import pytest

from digital_bast.application.services import BatchResult
from digital_bast.domain.reference import HolidayInput
from digital_bast.flows.models import Operation, Period, StepSummary
from digital_bast.flows.production import (
    HolidaySyncOperation,
    ProductionOperationUnavailableError,
    ProductionRunContext,
)

if TYPE_CHECKING:
    from digital_bast.domain.models import DomainRecord


class HolidaySourceStub:
    def load(self, _year: int) -> tuple[HolidayInput, ...]:
        return (HolidayInput(Period.parse("2026-08").start, "Test Holiday"),)


class RecordUpserterSpy:
    def __init__(self) -> None:
        self.records: tuple[DomainRecord, ...] = ()

    async def upsert(self, records: tuple[DomainRecord, ...]) -> BatchResult:
        self.records = records
        return BatchResult(created_or_updated=1, unchanged=0, locked=0)


class ProductionOperationStub:
    def __init__(self, operation: Operation) -> None:
        self.operation = operation

    async def execute(self, _period: Period) -> StepSummary:
        return StepSummary(operation=self.operation, read=2, written=1)


@pytest.mark.asyncio
async def test_holiday_sync_transforms_indonesia_calendar_rows_and_upserts_them() -> None:
    records = RecordUpserterSpy()
    context = ProductionRunContext(
        operations={Operation.HOLIDAY_SYNC: HolidaySyncOperation(HolidaySourceStub(), records)},
    )

    summary = await context.execute(Operation.HOLIDAY_SYNC, Period.parse("2026-08"))

    assert summary.operation is Operation.HOLIDAY_SYNC
    assert summary.read == 1
    assert summary.written == 1
    assert records.records[0].name == "Test Holiday"


@pytest.mark.asyncio
async def test_context_dispatches_an_enabled_production_operation() -> None:
    context = ProductionRunContext(
        operations={
            Operation.IOT_TASK_IMPORT: ProductionOperationStub(Operation.IOT_TASK_IMPORT),
        }
    )

    summary = await context.execute(Operation.IOT_TASK_IMPORT, Period.parse("2026-08"))

    assert summary.operation is Operation.IOT_TASK_IMPORT
    assert summary.written == 1


@pytest.mark.asyncio
async def test_iot_pic_update_fails_without_legacy_nocodb_database_adapter() -> None:
    context = ProductionRunContext()

    with pytest.raises(ProductionOperationUnavailableError, match="legacy NocoDB PostgreSQL DSN"):
        await context.execute(Operation.IOT_PIC_UPDATE, Period.parse("2026-08"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(Operation))
async def test_every_operation_fails_explicitly_without_its_production_adapter(
    operation: Operation,
) -> None:
    context = ProductionRunContext()

    with pytest.raises(ProductionOperationUnavailableError, match=operation.value):
        await context.execute(operation, Period.parse("2026-08"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [Operation.ATTENDANCE_IMPORT, Operation.REDMINE_IMPORT],
)
async def test_disabled_operation_returns_an_authorized_zero_summary(
    operation: Operation,
) -> None:
    context = ProductionRunContext(frozenset({operation}))

    summary = await context.execute(operation, Period.parse("2026-08"))

    assert summary.operation is operation
    assert summary.read == 0
    assert summary.written == 0
    assert summary.unchanged == 0
    assert summary.locked == 0


def test_production_context_uses_utc_clock() -> None:
    context = ProductionRunContext()

    assert context.now().tzinfo is UTC
