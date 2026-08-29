from __future__ import annotations

from dataclasses import dataclass

from prefect.deployments.runner import RunnerDeployment
from prefect.schedules import Cron

from digital_bast.flows.notifications import pmo_notifications_flow
from digital_bast.flows.pipelines import (
    iot_pic_update_flow,
    monthly_timesheets_flow,
    nightly_reconciliation_flow,
    operational_import_flow,
    reference_data_flow,
)


@dataclass(frozen=True, slots=True)
class DeploymentSchedule:
    name: str
    cron: str
    timezone: str = "Asia/Jakarta"
    concurrency_limit: int = 1


_SCHEDULES: tuple[DeploymentSchedule, ...] = (
    DeploymentSchedule("operational-import", "*/15 * * * *"),
    DeploymentSchedule("pmo-notifications", "*/15 * * * *"),
    DeploymentSchedule("nightly-reconciliation", "30 2 * * *"),
    DeploymentSchedule("reference-data", "15 0 * * *"),
    DeploymentSchedule("monthly-timesheets", "30 0 1 * *"),
    DeploymentSchedule("iot-pic-update", "0 1 * * *"),
)


def deployment_schedules() -> tuple[DeploymentSchedule, ...]:
    return _SCHEDULES


def build_deployments() -> tuple[RunnerDeployment, ...]:
    operational, notifications, reconciliation, references, timesheets, iot_pic = _SCHEDULES
    return (
        RunnerDeployment.from_flow(
            operational_import_flow,
            name=operational.name,
            schedule=Cron(operational.cron, timezone=operational.timezone),
            concurrency_limit=operational.concurrency_limit,
        ),
        RunnerDeployment.from_flow(
            pmo_notifications_flow,
            name=notifications.name,
            schedule=Cron(notifications.cron, timezone=notifications.timezone),
            concurrency_limit=notifications.concurrency_limit,
        ),
        RunnerDeployment.from_flow(
            nightly_reconciliation_flow,
            name=reconciliation.name,
            schedule=Cron(reconciliation.cron, timezone=reconciliation.timezone),
            concurrency_limit=reconciliation.concurrency_limit,
        ),
        RunnerDeployment.from_flow(
            reference_data_flow,
            name=references.name,
            schedule=Cron(references.cron, timezone=references.timezone),
            concurrency_limit=references.concurrency_limit,
        ),
        RunnerDeployment.from_flow(
            monthly_timesheets_flow,
            name=timesheets.name,
            schedule=Cron(timesheets.cron, timezone=timesheets.timezone),
            concurrency_limit=timesheets.concurrency_limit,
        ),
        RunnerDeployment.from_flow(
            iot_pic_update_flow,
            name=iot_pic.name,
            schedule=Cron(iot_pic.cron, timezone=iot_pic.timezone),
            concurrency_limit=iot_pic.concurrency_limit,
        ),
    )
