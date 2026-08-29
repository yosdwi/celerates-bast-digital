from __future__ import annotations

from digital_bast.flows.deployments import build_deployments, deployment_schedules


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
    }
