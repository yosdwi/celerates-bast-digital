"""Durable ordered attendance identities for reminder-driven Talent DMs.

This state is intentionally separate from both the legacy evidence-selection
TTL (``bot_conversations.updated_at``) and ``TalentConversationContext``.
A reminder snapshot stores only stable identity/context needed to interpret a
later reply. Current attendance facts are always re-read before a mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final
from uuid import UUID, uuid4

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from digital_bast.infrastructure.errors import InfrastructureError

_CONTEXT_VERSION = 1
_MAX_ATTENDANCE_KEYS = 64
_EMPTY_EMPLOYEE_ID = "employee_id must not be blank"
_EMPTY_CYCLE_ID = "cycle_id must not be blank"
_EMPTY_ATTENDANCE_KEYS = "attendance_keys must not be empty"
_TOO_MANY_ATTENDANCE_KEYS = "attendance_keys exceeds the supported snapshot size"
_DUPLICATE_ATTENDANCE_KEYS = "attendance_keys must be unique"
_INVALID_ATTENDANCE_KEY = "attendance_keys must contain non-empty strings"
_INVALID_VERSION = "version must be greater than zero"
_NAIVE_EXPIRY = "expires_at must be timezone-aware"


@dataclass(frozen=True, slots=True)
class AttendanceReminderContext:
    context_id: UUID
    version: int
    employee_id: str
    cycle_id: str
    attendance_keys: tuple[str, ...]
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError(_INVALID_VERSION)
        if not self.employee_id.strip():
            raise ValueError(_EMPTY_EMPLOYEE_ID)
        if not self.cycle_id.strip():
            raise ValueError(_EMPTY_CYCLE_ID)
        if not self.attendance_keys:
            raise ValueError(_EMPTY_ATTENDANCE_KEYS)
        if len(self.attendance_keys) > _MAX_ATTENDANCE_KEYS:
            raise ValueError(_TOO_MANY_ATTENDANCE_KEYS)
        if any(not key.strip() for key in self.attendance_keys):
            raise ValueError(_INVALID_ATTENDANCE_KEY)
        if len(set(self.attendance_keys)) != len(self.attendance_keys):
            raise ValueError(_DUPLICATE_ATTENDANCE_KEYS)
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError(_NAIVE_EXPIRY)

    @classmethod
    def create(
        cls,
        employee_id: str,
        cycle_id: str,
        attendance_keys: tuple[str, ...],
        expires_at: datetime,
        *,
        version: int = _CONTEXT_VERSION,
        context_id: UUID | None = None,
    ) -> AttendanceReminderContext:
        return cls(
            context_id=context_id or uuid4(),
            version=version,
            employee_id=employee_id,
            cycle_id=cycle_id,
            attendance_keys=attendance_keys,
            expires_at=expires_at,
        )

    def attendance_key_at(self, position: int) -> str | None:
        """Resolve a user-visible 1-based position against the sent snapshot."""
        if position < 1 or position > len(self.attendance_keys):
            return None
        return self.attendance_keys[position - 1]

    def is_expired(self, now: datetime | None = None) -> bool:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError(_NAIVE_EXPIRY)
        return self.expires_at <= instant


class _AttendanceContextRow:
    __slots__ = (
        "attendance_keys",
        "context_id",
        "cycle_id",
        "employee_id",
        "expires_at",
        "version",
    )

    def __init__(
        self,
        context_id: UUID,
        version: int,
        employee_id: str,
        cycle_id: str,
        attendance_keys: object,
        expires_at: datetime,
    ) -> None:
        self.context_id = context_id
        self.version = version
        self.employee_id = employee_id
        self.cycle_id = cycle_id
        self.attendance_keys = attendance_keys
        self.expires_at = expires_at


def _keys_from_json(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    if any(not isinstance(item, str) for item in value):
        return None
    return tuple(value)


@final
class AttendanceReminderContextService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def load(
        self,
        wa_jid: str,
        *,
        now: datetime | None = None,
    ) -> AttendanceReminderContext | None:
        return await run_sync(self._load, wa_jid, now)

    async def save(self, wa_jid: str, context: AttendanceReminderContext) -> None:
        await run_sync(self._save, wa_jid, context)

    async def clear(self, wa_jid: str) -> None:
        await run_sync(self._clear, wa_jid)

    def _load(
        self,
        wa_jid: str,
        now: datetime | None = None,
    ) -> AttendanceReminderContext | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_AttendanceContextRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT attendance_context_id AS context_id,
                           attendance_context_version AS version,
                           attendance_context_employee_id AS employee_id,
                           attendance_context_cycle_id AS cycle_id,
                           attendance_context_keys AS attendance_keys,
                           attendance_context_expires_at AS expires_at
                    FROM bot_conversations
                    WHERE wa_jid = %s
                      AND attendance_context_id IS NOT NULL
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="load_attendance_reminder_context"
            ) from error
        if row is None:
            return None

        keys = _keys_from_json(row.attendance_keys)
        if keys is None:
            return None
        try:
            context = AttendanceReminderContext(
                context_id=row.context_id,
                version=row.version,
                employee_id=row.employee_id,
                cycle_id=row.cycle_id,
                attendance_keys=keys,
                expires_at=row.expires_at,
            )
        except (TypeError, ValueError):
            # The database constraint protects normal writes. If a historical
            # or manually-edited row is malformed, fail closed instead of
            # letting it reinterpret a Talent reply.
            return None
        return None if context.is_expired(now) else context

    def _save(self, wa_jid: str, context: AttendanceReminderContext) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (
                        wa_jid,
                        attendance_context_id,
                        attendance_context_version,
                        attendance_context_employee_id,
                        attendance_context_cycle_id,
                        attendance_context_keys,
                        attendance_context_expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        attendance_context_id = EXCLUDED.attendance_context_id,
                        attendance_context_version = EXCLUDED.attendance_context_version,
                        attendance_context_employee_id = EXCLUDED.attendance_context_employee_id,
                        attendance_context_cycle_id = EXCLUDED.attendance_context_cycle_id,
                        attendance_context_keys = EXCLUDED.attendance_context_keys,
                        attendance_context_expires_at = EXCLUDED.attendance_context_expires_at
                    """,
                    (
                        wa_jid,
                        context.context_id,
                        context.version,
                        context.employee_id,
                        context.cycle_id,
                        Jsonb(list(context.attendance_keys)),
                        context.expires_at,
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="save_attendance_reminder_context"
            ) from error

    def _clear(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET attendance_context_id = NULL,
                        attendance_context_version = NULL,
                        attendance_context_employee_id = NULL,
                        attendance_context_cycle_id = NULL,
                        attendance_context_keys = NULL,
                        attendance_context_expires_at = NULL
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="clear_attendance_reminder_context"
            ) from error
