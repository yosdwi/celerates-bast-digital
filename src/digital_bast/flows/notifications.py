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
    celerates = await _celerates_campaign_tick()

    return {
        "pmo": asdict(pmo),
        "payroll": asdict(payroll),
        "payroll_digest": asdict(payroll_digest),
        "bast": asdict(bast),
        "bast_digest": asdict(bast_digest),
        "celerates_campaigns": celerates,
    }


async def _celerates_campaign_tick() -> dict[str, object]:
    """One bounded dispatch tick for approved Celerates campaigns.

    See docs/celerates-integration-v1.md.

    Unconfigured integration is a no-op, never an error for the other campaigns.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from digital_bast.web.celerates_router import configured_services  # noqa: PLC0415

    services = configured_services()
    if services is None:
        return {"configured": False}
    report = await services.campaigns.dispatch(now=lambda: datetime.now(UTC))
    return {
        "configured": True,
        "killed": report.killed,
        "campaigns": [
            {"id": str(tick.campaign_id), "sent": tick.sent, "state": tick.state.value}
            for tick in report.campaigns
        ],
    }
