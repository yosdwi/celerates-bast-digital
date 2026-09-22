from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from prefect import flow

from digital_bast.bast_runtime import (
    create_bast_group_digest_service,
    create_bast_talent_reminder_service,
)
from digital_bast.operations import create_pmo_notification_service
from digital_bast.payroll_runtime import (
    create_payroll_group_digest_service,
    create_payroll_talent_reminder_service,
)

if TYPE_CHECKING:
    from digital_bast.application.pmo_notifications import NotificationRunSummary
    from digital_bast.application.talent_reminders import TalentReminderRunSummary


@flow(
    name="pmo-notifications",
    validate_parameters=False,
    persist_result=False,
    timeout_seconds=600,
)
async def pmo_notifications_flow(scope_key: str = "default") -> dict[str, object]:
    """Run PMO notifications plus independent Payroll and BAST campaigns."""
    pmo: NotificationRunSummary = await create_pmo_notification_service(scope_key).run()
    payroll = await create_payroll_talent_reminder_service(scope_key).run()
    payroll_digest = await create_payroll_group_digest_service(scope_key).run()
    bast: TalentReminderRunSummary = await create_bast_talent_reminder_service(scope_key).run()
    bast_digest = await create_bast_group_digest_service(scope_key).run()

    return {
        "pmo": asdict(pmo),
        "payroll": asdict(payroll),
        "payroll_digest": asdict(payroll_digest),
        "bast": asdict(bast),
        "bast_digest": asdict(bast_digest),
    }
