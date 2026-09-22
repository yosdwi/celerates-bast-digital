"""Production wiring for the independent BAST closing campaign."""

from __future__ import annotations

from pydantic import ValidationError

from digital_bast.application.bast_closing import BastClosingControlService
from digital_bast.application.bast_snapshot import BastClosingSnapshotService
from digital_bast.application.talent_reminders import TalentReminderService
from digital_bast.application.talentops import TalentOpsService
from digital_bast.application.talentops_followups import TalentOpsFollowUpService
from digital_bast.bot.attendance_resolution import AttendanceResolutionService
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.infrastructure.completion_source import CompletionSource
from digital_bast.infrastructure.local_completion_source import (
    PostgresAttendanceFactReader,
    PostgresTaskEvidenceReader,
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


def create_bast_talent_reminder_service(scope_key: str = "default") -> TalentReminderService:
    try:
        settings = get_settings()
    except (ValidationError, SettingsConfigurationError, OSError) as error:
        raise RuntimeError("BAST closing settings unavailable") from error
    if settings.database_dsn is None:
        raise RuntimeError("APP_DATABASE_DSN is required for BAST closing")

    dsn = settings.database_dsn.get_secret_value()
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

    outbound: BotBridgeWhatsAppOutboundGateway | UnavailableWhatsAppOutboundGateway
    if settings.bot_bridge_base_url is None or settings.sync_ingest_token is None:
        outbound = UnavailableWhatsAppOutboundGateway()
    else:
        outbound = BotBridgeWhatsAppOutboundGateway(
            str(settings.bot_bridge_base_url),
            settings.sync_ingest_token.get_secret_value(),
            timeout_seconds=settings.outbound_timeout_seconds,
        )

    followups = TalentOpsFollowUpService(
        talentops,
        employees,
        PostgresWhatsAppIdentityResolver(dsn),
        outbound,
        PostgresTalentOpsFollowUpRepository(dsn),
        ai=None,
    )
    return TalentReminderService(
        scope_key,
        BastClosingControlService(dsn),
        snapshot,
        followups,
    )