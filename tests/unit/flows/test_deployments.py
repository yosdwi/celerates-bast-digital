from __future__ import annotations

from digital_bast.flows.deployments import build_deployments, deployment_schedules
from digital_bast.flows.housekeeping import prefect_housekeeping_flow
from digital_bast.flows.notifications import pmo_notifications_flow
from digital_bast.flows.pipelines import (
    iot_pic_update_flow,
    monthly_timesheets_flow,
    nightly_reconciliation_flow,
    operational_import_flow,
    reference_data_flow,
)


def test_every_scheduled_business_flow_uses_jakarta_and_single_concurrency() -> None:
    schedules = deployment_schedules()

    assert schedules
    assert all(schedule.concurrency_limit == 1 for schedule in schedules)
    assert all(schedule.timezone == "Asia/Jakarta" for schedule in schedules)
    assert all(deployment.concurrency_limit == 1 for deployment in build_deployments())


def test_operational_import_never_exceeds_fifteen_minute_interval() -> None:
    operational = next(item for item in deployment_schedules() if item.name == "operational-import")

    assert operational.cron == "*/15 * * * *"


def test_pmo_notifications_run_every_fifteen_minutes() -> None:
    notifications = next(
        item for item in deployment_schedules() if item.name == "pmo-notifications"
    )

    assert notifications.cron == "*/15 * * * *"
    assert notifications.timezone == "Asia/Jakarta"
    assert notifications.concurrency_limit == 1


def test_step10_runs_at_exactly_one_am_jakarta() -> None:
    step10 = next(item for item in deployment_schedules() if item.name == "iot-pic-update")

    assert step10.cron == "0 1 * * *"
    assert step10.timezone == "Asia/Jakarta"


def test_deployment_registry_excludes_obsolete_and_redundant_steps() -> None:
    names = {schedule.name for schedule in deployment_schedules()}

    assert names == {
        "operational-import",
        "pmo-notifications",
        "nightly-reconciliation",
        "reference-data",
        "monthly-timesheets",
        "iot-pic-update",
        "prefect-housekeeping",
    }


def test_every_scheduled_business_flow_has_a_timeout() -> None:
    # A run stuck without a timeout can occupy its deployment's single
    # concurrency slot forever, so every scheduled run behind it piles up
    # unexecuted -- exactly what happened on 2026-08-25 (1,374 backlogged
    # runs from one hung operational-import run). Every flow that gets a
    # schedule in deployments.py must cap how long a single run can run.
    for flow in (
        operational_import_flow,
        pmo_notifications_flow,
        nightly_reconciliation_flow,
        reference_data_flow,
        monthly_timesheets_flow,
        iot_pic_update_flow,
        prefect_housekeeping_flow,
    ):
        assert flow.timeout_seconds is not None
        assert flow.timeout_seconds > 0


def test_housekeeping_runs_hourly() -> None:
    housekeeping = next(
        item for item in deployment_schedules() if item.name == "prefect-housekeeping"
    )

    assert housekeeping.cron == "0 * * * *"
    assert housekeeping.timezone == "Asia/Jakarta"
    assert housekeeping.concurrency_limit == 1
