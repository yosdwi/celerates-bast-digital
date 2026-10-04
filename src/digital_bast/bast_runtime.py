"""Production wiring for the independent BAST closing campaign."""

from __future__ import annotations

from pydantic import ValidationError

from digital_bast.application.bast_closing import BastClosingControlService
from digital_bast.application.bast_group_digest import BastGroupDigestService
from digital_bast.application.bast_snapshot import BastClosingSnapshotService
from digital_bast.application.talent_reminders import TalentReminderService
from digital_bast.application.talentops import TalentOpsService
from digital_bast.application.talentops_followups import TalentOpsFollowUpService
from digital_bast.application.workflow_control import WorkflowControlService
from digital_bast.bot.attendance_resolution import AttendanceResolutionService
from digital_bast.bot.bast_reminder_context import BastReminderContextService
from digital_bast.config import Settings, SettingsConfigurationError, get_settings
from digital_bast.infrastructure.completion_source import CompletionSource
from digital_bast.infrastructure.local_completion_source import (
    PostgresAttendanceFactReader,
    PostgresTaskEvidenceReader,
)
from digital_bast.infrastructure.payroll_group_digest import (
    PostgresPayrollGroupDigestDeliveryStore,
)
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.infrastructure.source_sync_state import PostgresSourceSyncStateStore
from digital_bast.infrastructure.talentops_followup_store import (
    PostgresTalentOpsFollowUpRepository,
    PostgresWhatsAppIdentityResolver,
)
from digital_bast.infrastructure.whatsapp_outbound import (
    BotBridgeWhatsAppOutboundGateway,
    UnavailableWhatsAppOutboundGateway,
)

OutboundGateway = BotBridgeWhatsAppOutboundGateway | UnavailableWhatsAppOutboundGateway
_SETTINGS_UNAVAILABLE = "BAST closing settings unavailable"
_DATABASE_REQUIRED = "APP_DATABASE_DSN is required for BAST closing"


def _settings_and_dsn() -> tuple[Settings, str]:
    try:
        settings = get_settings()
    except (ValidationError, SettingsConfigurationError, OSError) as error:
        raise RuntimeError(_SETTINGS_UNAVAILABLE) from error
    if settings.database_dsn is None:
        raise RuntimeError(_DATABASE_REQUIRED)
    return settings, settings.database_dsn.get_secret_value()


def _configured_dsn() -> str:
    return _settings_and_dsn()[1]


def _outbound(settings: Settings) -> OutboundGateway:
    if settings.bot_bridge_base_url is None or settings.sync_ingest_token is None:
        return UnavailableWhatsAppOutboundGateway()
    return BotBridgeWhatsAppOutboundGateway(
        str(settings.bot_bridge_base_url),
        settings.sync_ingest_token.get_secret_value(),
        timeout_seconds=settings.outbound_timeout_seconds,
    )


def create_bast_snapshot_service(scope_key: str = "default") -> BastClosingSnapshotService:
    dsn = _configured_dsn()
    employees = PostgresEmployeeSource(dsn)
    records = PostgresDomainRepository(dsn)
    evidence = PostgresTaskEvidenceReader(dsn, scope_key=scope_key)
    completion = CompletionSource(
        employees,
        records,
        PostgresAttendanceFactReader(dsn),
        evidence,
    )
    talentops = TalentOpsService(
        completion,
        employees,
        records,
        PostgresSourceSyncStateStore(dsn),
    )
    return BastClosingSnapshotService(talentops, AttendanceResolutionService(dsn))


def create_bast_talent_reminder_service(scope_key: str = "default") -> TalentReminderService:
    settings, dsn = _settings_and_dsn()
    employees = PostgresEmployeeSource(dsn)
    records = PostgresDomainRepository(dsn)
    evidence = PostgresTaskEvidenceReader(dsn, scope_key=scope_key)
    completion = CompletionSource(
        employees,
        records,
        PostgresAttendanceFactReader(dsn),
        evidence,
    )
    talentops = TalentOpsService(
        completion,
        employees,
        records,
        PostgresSourceSyncStateStore(dsn),
    )
    snapshot = BastClosingSnapshotService(talentops, AttendanceResolutionService(dsn))
    followups = TalentOpsFollowUpService(
        talentops,
        employees,
        PostgresWhatsAppIdentityResolver(dsn),
        _outbound(settings),
        PostgresTalentOpsFollowUpRepository(dsn),
        ai=None,
    )
    return TalentReminderService(
        scope_key,
        BastClosingControlService(dsn),
        snapshot,
        followups,
        BastReminderContextService(dsn),
    )


def create_bast_group_digest_service(scope_key: str = "default") -> BastGroupDigestService:
    settings, dsn = _settings_and_dsn()
    return BastGroupDigestService(
        scope_key,
        BastClosingControlService(dsn),
        create_bast_snapshot_service(scope_key),
        _outbound(settings),
        PostgresPayrollGroupDigestDeliveryStore(dsn),
        WorkflowControlService(dsn),
    )
