from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from prefect import flow

from digital_bast.operations import (
    create_pmo_notification_service,
    create_talent_reminder_service,
)

if TYPE_CHECKING:
    from digital_bast.application.pmo_notifications import NotificationRunSummary
    from digital_bast.application.talent_reminders import TalentReminderRunSummary


@flow(
    name="pmo-notifications",
    validate_parameters=False,
    persist_result=False,
    # Same 15-minute-cadence / concurrency_limit=1 reasoning as
    # operational-import (flows/pipelines.py): a hung run must not be able to
    # occupy the slot forever and stall every run behind it.
    timeout_seconds=600,
)
async def pmo_notifications_flow(scope_key: str = "default") -> dict[str, object]:
    """Run PMO queue notifications and configured Talent reminders for one scope."""
    pmo: NotificationRunSummary = await create_pmo_notification_service(scope_key).run()
    talent: TalentReminderRunSummary = await create_talent_reminder_service(scope_key).run()
    return {
        "pmo": asdict(pmo),
        "talent": asdict(talent),
    }
