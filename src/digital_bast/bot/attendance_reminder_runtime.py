"""Runtime assembly for Payroll reminder DM routing and response correlation."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from digital_bast.application.payroll_read import PayrollReadService
from digital_bast.bot.attendance_context import AttendanceReminderContextService
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderRouteStatus,
    AttendanceReminderRoutingService,
)
from digital_bast.config import get_settings
from digital_bast.infrastructure.payroll_attendance import PostgresPayrollAttendanceReader
from digital_bast.infrastructure.payroll_reminder_delivery import (
    PostgresPayrollReminderDeliveryStore,
)
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.operations import OperationConfigurationError

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.bot.attendance_context import AttendanceReminderContext
    from digital_bast.bot.attendance_reminder_routing import AttendanceReminderRouteResult

_MISSING_APP_DSN = "APP_DATABASE_DSN"


def _application_dsn() -> str:
    settings = get_settings()
    if settings.database_dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return settings.database_dsn.get_secret_value()


def create_attendance_reminder_context_service() -> AttendanceReminderContextService:
    return AttendanceReminderContextService(_application_dsn())


@final
class TrackedAttendanceReminderRoutingService:
    """Record only a valid attendance action against a successfully sent reminder."""

    def __init__(
        self,
        routing: AttendanceReminderRoutingService,
        deliveries: PostgresPayrollReminderDeliveryStore,
    ) -> None:
        self._routing = routing
        self._deliveries = deliveries

    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        result = await self._routing.first_actionable(
            context,
            employee_id=employee_id,
            now=now,
        )
        if result.status is AttendanceReminderRouteStatus.OPEN:
            _ = await self._deliveries.mark_attendance_response(
                context_id=context.context_id,
                employee_id=employee_id,
                responded_at=now,
            )
        return result


def create_attendance_reminder_routing_service() -> TrackedAttendanceReminderRoutingService:
    dsn = _application_dsn()
    routing = AttendanceReminderRoutingService(
        PayrollReadService(
            PostgresEmployeeSource(dsn),
            PostgresDomainRepository(dsn),
            PostgresPayrollAttendanceReader(dsn),
        )
    )
    return TrackedAttendanceReminderRoutingService(
        routing,
        PostgresPayrollReminderDeliveryStore(dsn),
    )
