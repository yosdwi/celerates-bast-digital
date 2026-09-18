"""Delete stale SCHEDULED runs for the frequently-scheduled deployments.

`operational-import` and `pmo-notifications` run every 15 minutes with
`concurrency_limit=1` (deployments.py). Each run re-syncs whatever "now" is
when it executes (resolve_period/current_period default to the run's own
clock), so a scheduled slot that's hours overdue has no data value once it's
that stale -- the next tick covers the same ground.

`timeout_seconds` on those two flows (pipelines.py, notifications.py) is the
real fix for what caused this once already: a run hung in RUNNING forever
occupied the one concurrency slot for three weeks (2026-08-25 incident),
during which the scheduler kept quietly generating future SCHEDULED runs
that could never execute, and by the time the slot freed up 1,374 of them
had piled up needing a manual purge. This flow is the second layer -- it
deletes that kind of backlog automatically before it can grow large enough
to matter, in case a run ever again occupies the slot far longer than
expected for some other reason.

Deliberately scoped to only these two deployments: the daily/monthly ones
(nightly-reconciliation, reference-data, monthly-timesheets, iot-pic-update)
run once a day or less, so a run that's a couple of hours overdue (e.g. the
worker was down for a deploy) is still worth executing, not staleness to
discard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from prefect import flow, get_run_logger
from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import (
    DeploymentFilter,
    DeploymentFilterName,
    FlowRunFilter,
    FlowRunFilterExpectedStartTime,
    FlowRunFilterState,
    FlowRunFilterStateType,
)
from prefect.client.schemas.objects import StateType

_HIGH_FREQUENCY_DEPLOYMENTS: Final = ("operational-import", "pmo-notifications")
_STALE_AFTER: Final = timedelta(hours=1)
# Bounds how long one housekeeping run can spend deleting, so a very large
# backlog (if this ever falls behind) drains over a few runs rather than
# risking this flow itself running long.
_MAX_DELETE_PER_RUN: Final = 5000
_PAGE_SIZE: Final = 200


@flow(
    name="prefect-housekeeping",
    validate_parameters=False,
    persist_result=False,
    timeout_seconds=600,
)
async def prefect_housekeeping_flow() -> int:
    logger = get_run_logger()
    cutoff = datetime.now(UTC) - _STALE_AFTER
    deleted = 0
    async with get_client() as client:
        while deleted < _MAX_DELETE_PER_RUN:
            runs = await client.read_flow_runs(
                flow_run_filter=FlowRunFilter(
                    state=FlowRunFilterState(
                        type=FlowRunFilterStateType(any_=[StateType.SCHEDULED])
                    ),
                    expected_start_time=FlowRunFilterExpectedStartTime(before_=cutoff),
                ),
                deployment_filter=DeploymentFilter(
                    name=DeploymentFilterName(any_=list(_HIGH_FREQUENCY_DEPLOYMENTS))
                ),
                limit=_PAGE_SIZE,
            )
            if not runs:
                break
            for run in runs:
                await client.delete_flow_run(run.id)
                deleted += 1
    logger.info(
        f"deleted {deleted} stale scheduled runs "
        f"(overdue by more than {_STALE_AFTER}) for {_HIGH_FREQUENCY_DEPLOYMENTS}"
    )
    return deleted
