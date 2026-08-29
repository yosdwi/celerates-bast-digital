from __future__ import annotations

from prefect import flow

from digital_bast.application.pmo_notifications import NotificationRunSummary
from digital_bast.operations import create_pmo_notification_service


@flow(name="pmo-notifications", validate_parameters=False, persist_result=False)
async def pmo_notifications_flow(scope_key: str = "default") -> NotificationRunSummary:
    """Enqueue and deliver low-noise PMO WhatsApp notifications for one scope."""
    return await create_pmo_notification_service(scope_key).run()
