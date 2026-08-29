from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from digital_bast.application.bast_workflow import BastWorkflowService
    from digital_bast.application.talentops import TalentOpsService
    from digital_bast.application.talentops_ai import TalentOpsAiService
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService
    from digital_bast.application.workflow_control import WorkflowControlService
    from digital_bast.bot.attendance_resolution import AttendanceResolutionService
    from digital_bast.bot.rebind import IdentityRebindService
    from digital_bast.infrastructure.source_sync_state import PostgresSourceSyncStateStore
    from digital_bast.infrastructure.whatsapp_outbound import BotBridgeWhatsAppOutboundGateway
    from digital_bast.web.contracts import OwnerAuthenticator, SessionStore, WebBackend
    from digital_bast.web.security import CookieSettings


@dataclass(frozen=True, slots=True)
class WebDependencies:
    authenticator: OwnerAuthenticator
    sessions: SessionStore
    backend: WebBackend
    cookie: CookieSettings
    talentops: TalentOpsService | None = None
    talentops_ai: TalentOpsAiService | None = None
    talentops_followups: TalentOpsFollowUpService | None = None
    attendance_resolutions: AttendanceResolutionService | None = None
    workflow_control: WorkflowControlService | None = None
    identity_rebinds: IdentityRebindService | None = None
    bast_workflow: BastWorkflowService | None = None
    source_sync_state: PostgresSourceSyncStateStore | None = None
    bot_bridge_status: BotBridgeWhatsAppOutboundGateway | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    session_id: Callable[[], str] = lambda: secrets.token_urlsafe(32)
