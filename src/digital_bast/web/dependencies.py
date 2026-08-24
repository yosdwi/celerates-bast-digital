from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from digital_bast.web.contracts import OwnerAuthenticator, SessionStore, WebBackend
from digital_bast.web.security import CookieSettings

if TYPE_CHECKING:
    from digital_bast.application.talentops import TalentOpsService
    from digital_bast.application.talentops_ai import TalentOpsAiService
    from digital_bast.infrastructure.source_sync_state import PostgresSourceSyncStateStore


@dataclass(frozen=True, slots=True)
class WebDependencies:
    authenticator: OwnerAuthenticator
    sessions: SessionStore
    backend: WebBackend
    cookie: CookieSettings
    talentops: TalentOpsService | None = None
    talentops_ai: TalentOpsAiService | None = None
    source_sync_state: PostgresSourceSyncStateStore | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    session_id: Callable[[], str] = lambda: secrets.token_urlsafe(32)
