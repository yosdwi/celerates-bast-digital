"""Short-lived conversational context for bound Talent WhatsApp DMs.

The context remembers only navigation intent + reporting period. It never stores
or derives readiness/business decisions, and it is deliberately independent of
bot_conversations.updated_at so natural-language chat cannot extend the legacy
evidence-selection TTL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.domain.completion import DateRange
from digital_bast.infrastructure.errors import InfrastructureError

_CONTEXT_TTL_SECONDS = 30 * 60
_INVALID_CONTEXT_INTENT = "intent is not persistable Talent context"


class TalentIntent(StrEnum):
    HOME = "home"
    ATTENDANCE = "attendance"
    TASKS = "tasks"
    STATUS = "status"
    REQUESTS = "requests"
    GROUP_ONLY = "group_only"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


_CONTEXT_INTENTS = frozenset(
    {
        TalentIntent.HOME,
        TalentIntent.ATTENDANCE,
        TalentIntent.TASKS,
        TalentIntent.STATUS,
        TalentIntent.REQUESTS,
    }
)


@dataclass(frozen=True, slots=True)
class TalentConversationContext:
    intent: TalentIntent
    period: DateRange

    def __post_init__(self) -> None:
        if self.intent not in _CONTEXT_INTENTS:
            raise ValueError(_INVALID_CONTEXT_INTENT)


@dataclass(frozen=True, slots=True)
class TalentInterpretation:
    intent: TalentIntent
    period: DateRange | None = None


class _ContextRow:
    __slots__ = ("end_date", "intent", "start_date")

    def __init__(self, intent: str, start_date: date, end_date: date) -> None:
        self.intent = intent
        self.start_date = start_date
        self.end_date = end_date


@final
class TalentConversationContextService:
    def __init__(
        self,
        dsn: str,
        connect_timeout_seconds: int = 5,
        ttl_seconds: int = _CONTEXT_TTL_SECONDS,
    ) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds
        self._ttl_seconds = ttl_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def load(self, wa_jid: str) -> TalentConversationContext | None:
        return await run_sync(self._load, wa_jid)

    async def save(self, wa_jid: str, context: TalentConversationContext) -> None:
        await run_sync(self._save, wa_jid, context)

    async def clear(self, wa_jid: str) -> None:
        await run_sync(self._clear, wa_jid)

    def _load(self, wa_jid: str) -> TalentConversationContext | None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self._ttl_seconds)
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_ContextRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT talent_context_intent AS intent,
                           talent_context_start_date AS start_date,
                           talent_context_end_date AS end_date
                    FROM bot_conversations
                    WHERE wa_jid = %s
                      AND talent_context_intent IS NOT NULL
                      AND talent_context_start_date IS NOT NULL
                      AND talent_context_end_date IS NOT NULL
                      AND talent_context_updated_at >= %s
                    """,
                    (wa_jid, cutoff),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="load_talent_conversation_context"
            ) from error
        if row is None:
            return None
        try:
            return TalentConversationContext(
                TalentIntent(row.intent),
                DateRange(row.start_date, row.end_date),
            )
        except ValueError:
            # Database constraints prevent this in normal operation. Fail safe
            # as "no context" rather than letting stale/corrupt navigation
            # state alter how a user message is interpreted.
            return None

    def _save(self, wa_jid: str, context: TalentConversationContext) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (
                        wa_jid,
                        talent_context_intent,
                        talent_context_start_date,
                        talent_context_end_date,
                        talent_context_updated_at
                    ) VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        talent_context_intent = EXCLUDED.talent_context_intent,
                        talent_context_start_date = EXCLUDED.talent_context_start_date,
                        talent_context_end_date = EXCLUDED.talent_context_end_date,
                        talent_context_updated_at = now()
                    """,
                    (
                        wa_jid,
                        context.intent.value,
                        context.period.start,
                        context.period.end,
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="save_talent_conversation_context"
            ) from error

    def _clear(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET talent_context_intent = NULL,
                        talent_context_start_date = NULL,
                        talent_context_end_date = NULL,
                        talent_context_updated_at = NULL
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="clear_talent_conversation_context"
            ) from error
