"""Runtime assembly for Payroll closing policy, delivery, and reminder dispatch."""

from __future__ import annotations

from digital_bast.application.payroll_digest import PayrollDigestService
from digital_bast.application.payroll_group_digest import PayrollGroupDigestService
from digital_bast.application.payroll_read import PayrollReadService
from digital_bast.application.payroll_reminders import PayrollTalentReminderService
from digital_bast.bot.attendance_context import AttendanceReminderContextService
from digital_bast.config import get_settings
from digital_bast.infrastructure.payroll_attendance import PostgresPayrollAttendanceReader
from digital_bast.infrastructure.payroll_closing_settings import (
    PostgresPayrollClosingSettingsStore,
)
from digital_bast.infrastructure.payroll_group_digest import (
    PostgresPayrollGroupDigestDeliveryStore,
)
from digital_bast.infrastructure.payroll_reminder_delivery import (
    PostgresPayrollReminderDeliveryStore,
)
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.infrastructure.talentops_followup_store import (
    PostgresWhatsAppIdentityResolver,
)
from digital_bast.infrastructure.whatsapp_directory import PostgresTalentWhatsAppDirectory
from digital_bast.infrastructure.whatsapp_outbound import (
    BotBridgeWhatsAppOutboundGateway,
    UnavailableWhatsAppOutboundGateway,
)
from digital_bast.operations import OperationConfigurationError

_MISSING_APP_DSN = "APP_DATABASE_DSN"


def _application_dsn() -> str:
    settings = get_settings()
    if settings.database_dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return settings.database_dsn.get_secret_value()


def _outbound_gateway() -> BotBridgeWhatsAppOutboundGateway | UnavailableWhatsAppOutboundGateway:
    settings = get_settings()
    token = settings.sync_ingest_token
    if settings.bot_bridge_base_url is None or token is None:
        return UnavailableWhatsAppOutboundGateway()
    return BotBridgeWhatsAppOutboundGateway(
        str(settings.bot_bridge_base_url),
        token.get_secret_value(),
        timeout_seconds=settings.outbound_timeout_seconds,
    )


def _payroll_read(dsn: str) -> PayrollReadService:
    return PayrollReadService(
        PostgresEmployeeSource(dsn),
        PostgresDomainRepository(dsn),
        PostgresPayrollAttendanceReader(dsn),
    )


def create_payroll_reminder_delivery_store() -> PostgresPayrollReminderDeliveryStore:
    return PostgresPayrollReminderDeliveryStore(_application_dsn())


def create_payroll_digest_service(scope_key: str = "default") -> PayrollDigestService:
    dsn = _application_dsn()
    return PayrollDigestService(
        scope_key,
        _payroll_read(dsn),
        PostgresPayrollReminderDeliveryStore(dsn),
    )


def create_payroll_talent_reminder_service(
    scope_key: str = "default",
) -> PayrollTalentReminderService:
    dsn = _application_dsn()
    return PayrollTalentReminderService(
        scope_key,
        PostgresPayrollClosingSettingsStore(dsn),
        _payroll_read(dsn),
        PostgresWhatsAppIdentityResolver(dsn),
        AttendanceReminderContextService(dsn),
        _outbound_gateway(),
        PostgresPayrollReminderDeliveryStore(dsn),
        PostgresPayrollAttendanceReader(dsn),
    )


def create_payroll_group_digest_service(
    scope_key: str = "default",
) -> PayrollGroupDigestService:
    dsn = _application_dsn()
    digest = PayrollDigestService(
        scope_key,
        _payroll_read(dsn),
        PostgresPayrollReminderDeliveryStore(dsn),
    )
    return PayrollGroupDigestService(
        scope_key,
        PostgresPayrollClosingSettingsStore(dsn),
        digest,
        PostgresTalentWhatsAppDirectory(dsn),
        _outbound_gateway(),
        PostgresPayrollGroupDigestDeliveryStore(dsn),
    )
