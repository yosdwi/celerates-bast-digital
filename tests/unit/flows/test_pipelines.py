from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from digital_bast.flows import Operation, Period, StepSummary, execute_pipeline
from digital_bast.flows.pipelines import (
    current_period,
    idempotent_operation,
    single_attempt_operation,
)


class FakeContext:
    def __init__(self, failing: Operation | None = None) -> None:
        self.failing = failing
        self.calls: list[Operation] = []
        self.keys: set[tuple[Operation, str]] = set()
        self.cursor_advances: list[Operation] = []

    def now(self) -> datetime:
        return datetime(2024, 3, 1, 0, 30, tzinfo=ZoneInfo("Asia/Jakarta"))

    async def execute(self, operation: Operation, period: Period) -> StepSummary:
        self.calls.append(operation)
        if operation is self.failing:
            raise SourceFailureError(operation)
        key = (operation, str(period))
        written = int(key not in self.keys)
        self.keys.add(key)
        self.cursor_advances.append(operation)
        return StepSummary(operation=operation, read=1, written=written, unchanged=1 - written)


class SourceFailureError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_operational_pipeline_is_idempotent_when_repeated() -> None:
    context = FakeContext()
    period = Period.parse("2024-02")
    operations = (Operation.ATTENDANCE_IMPORT, Operation.REDMINE_IMPORT)

    first = await execute_pipeline("operational-import", operations, period, context)
    second = await execute_pipeline("operational-import", operations, period, context)

    assert first.written == 2
    assert second.written == 0
    assert second.unchanged == 2


@pytest.mark.asyncio
async def test_pipeline_stops_and_does_not_advance_failed_source_cursor() -> None:
    context = FakeContext(failing=Operation.REDMINE_IMPORT)
    operations = (
        Operation.ATTENDANCE_IMPORT,
        Operation.REDMINE_IMPORT,
        Operation.IOT_TASK_IMPORT,
    )

    with pytest.raises(SourceFailureError):
        await execute_pipeline("operational-import", operations, Period.parse("2024-02"), context)

    assert context.calls == [Operation.ATTENDANCE_IMPORT, Operation.REDMINE_IMPORT]
    assert context.cursor_advances == [Operation.ATTENDANCE_IMPORT]


def test_only_idempotent_operations_are_retried() -> None:
    assert idempotent_operation.retries == 2
    assert single_attempt_operation.retries == 0


def test_current_period_uses_jakarta_calendar_independent_of_source_offset() -> None:
    context = FakeContext()

    assert current_period(context) == Period.parse("2024-03")
