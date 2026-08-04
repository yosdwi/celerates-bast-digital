from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final

from prefect import flow, task
from prefect.cache_policies import NO_CACHE

from digital_bast.domain.time import JAKARTA
from digital_bast.flows.models import Operation, Period, RunSummary, StepSummary
from digital_bast.flows.runtime import get_run_context

if TYPE_CHECKING:
    from digital_bast.flows.contracts import RunContext

_OPERATIONAL: tuple[Operation, ...] = (
    Operation.ATTENDANCE_IMPORT,
    Operation.REDMINE_IMPORT,
    Operation.IOT_TASK_IMPORT,
)
_REFERENCES: tuple[Operation, ...] = (Operation.HOLIDAY_SYNC, Operation.SCHEDULE_SYNC)
_SYNC_LOOKBACK_MONTHS: Final = 1


def current_period(context: RunContext | None = None) -> Period:
    now = context.now() if context is not None else datetime.now(JAKARTA)
    local = now.astimezone(JAKARTA)
    return Period(year=local.year, month=local.month, lookback_months=_SYNC_LOOKBACK_MONTHS)


def resolve_period(value: str | None, context: RunContext) -> Period:
    return current_period(context) if value is None else Period.parse(value)


async def execute_pipeline(
    name: str,
    operations: tuple[Operation, ...],
    period: Period,
    context: RunContext,
) -> RunSummary:
    completed = [await context.execute(operation, period) for operation in operations]
    steps = tuple(completed)
    return RunSummary(flow=name, period=period, steps=steps)


@task(
    name="idempotent-business-operation",
    retries=2,
    retry_delay_seconds=[5, 30],
    cache_policy=NO_CACHE,
)
async def idempotent_operation(
    context: RunContext,
    operation: Operation,
    period: Period,
) -> StepSummary:
    return await context.execute(operation, period)


@task(name="single-attempt-business-operation", retries=0, cache_policy=NO_CACHE)
async def single_attempt_operation(
    context: RunContext,
    operation: Operation,
    period: Period,
) -> StepSummary:
    return await context.execute(operation, period)


async def _run_tasks(
    name: str,
    operations: tuple[Operation, ...],
    period: Period,
    context: RunContext,
) -> RunSummary:
    completed = [await idempotent_operation(context, operation, period) for operation in operations]
    steps = tuple(completed)
    return RunSummary(flow=name, period=period, steps=steps)


@flow(name="operational-import", validate_parameters=False, persist_result=False)
async def operational_import_flow(
    period: str | None = None,
) -> RunSummary:
    active = get_run_context()
    target = resolve_period(period, active)
    return await _run_tasks("operational-import", _OPERATIONAL, target, active)


@flow(name="nightly-reconciliation", validate_parameters=False, persist_result=False)
async def nightly_reconciliation_flow(
    period: str | None = None,
) -> RunSummary:
    active = get_run_context()
    target = resolve_period(period, active)
    return await _run_tasks("nightly-reconciliation", (Operation.RECONCILIATION,), target, active)


@flow(name="reference-data", validate_parameters=False, persist_result=False)
async def reference_data_flow(
    period: str | None = None,
) -> RunSummary:
    active = get_run_context()
    target = resolve_period(period, active)
    return await _run_tasks("reference-data", _REFERENCES, target, active)


@flow(name="monthly-timesheets", validate_parameters=False, persist_result=False)
async def monthly_timesheets_flow(
    period: str | None = None,
) -> RunSummary:
    active = get_run_context()
    target = resolve_period(period, active)
    return await _run_tasks("monthly-timesheets", (Operation.TIMESHEET_GENERATION,), target, active)


@flow(name="iot-pic-update", validate_parameters=False, persist_result=False)
async def iot_pic_update_flow() -> RunSummary:
    active = get_run_context()
    target = current_period(active)
    step = await single_attempt_operation(active, Operation.IOT_PIC_UPDATE, target)
    return RunSummary(flow="iot-pic-update", period=target, steps=(step,))
