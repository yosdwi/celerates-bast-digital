"""Runtime assembly for Payroll reminder DM routing.

Kept separate from the large shared operations module so P09 can stay a small,
reviewable change. Business logic remains in attendance_reminder_routing.py.
"""

from __future__ import annotations

from digital_bast.application.payroll_read import PayrollReadService
from digital_bast.bot.attendance_context import AttendanceReminderContextService
from digital_bast.bot.attendance_reminder_routing import AttendanceReminderRoutingService
from digital_bast.config import get_settings
from digital_bast.infrastructure.payroll_attendance import PostgresPayrollAttendanceReader
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.operations import OperationConfigurationError

_MISSING_APP_DSN = "APP_DATABASE_DSN"


def _application_dsn() -> str:
    settings = get_settings()
    if settings.database_dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return settings.database_dsn.get_secret_value()


def create_attendance_reminder_context_service() -> AttendanceReminderContextService:
    return AttendanceReminderContextService(_application_dsn())


def create_attendance_reminder_routing_service() -> AttendanceReminderRoutingService:
    dsn = _application_dsn()
    return AttendanceReminderRoutingService(
        PayrollReadService(
            PostgresEmployeeSource(dsn),
            PostgresDomainRepository(dsn),
            PostgresPayrollAttendanceReader(dsn),
        )
    )
