"""Authorization and routing control plane for the Digital BAST workflow.

WhatsApp is only an interaction channel. PMO authority is provisioned here by
an admin and then linked to a WhatsApp JID with a one-time token. A phone number
can never self-select the PMO role.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from collections.abc import Sequence

_INVITE_PREFIX: Final = "PMO-"
_INVITE_TTL: Final = timedelta(hours=24)


class WorkflowRole(StrEnum):
    ADMIN = "admin"
    PMO = "pmo"


@dataclass(frozen=True, slots=True)
class WorkflowOperator:
    email: str
    display_name: str
    role: WorkflowRole
    scope_key: str
    active: bool
    can_approve_attendance: bool
    can_approve_rebind: bool
    can_generate_bast: bool
    whatsapp_notify: bool
    whatsapp_jid: str | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppInvite:
    token: str
    operator_email: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    scope_key: str
    attendance_immediate: bool
    rebind_immediate: bool
    digest_enabled: bool
    digest_hour: int
    deadline_reminder_days: tuple[int, ...]


class InviteOutcome(StrEnum):
    LINKED = "linked"
    INVALID = "invalid"
    EXPIRED = "expired"
    USED = "used"
    INACTIVE = "inactive"
    JID_ALREADY_LINKED = "jid_already_linked"
    OPERATOR_ALREADY_LINKED = "operator_already_linked"


@dataclass(frozen=True, slots=True)
class InviteResult:
    outcome: InviteOutcome
    operator: WorkflowOperator | None = None


class _OperatorRow:
    __slots__ = (
        "active",
        "can_approve_attendance",
        "can_approve_rebind",
        "can_generate_bast",
        "display_name",
        "email",
        "role",
        "scope_key",
        "wa_jid",
        "whatsapp_notify",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors selected database columns
        self,
        email: str,
        display_name: str,
        role: str,
        scope_key: str,
        active: bool,
        can_approve_attendance: bool,
        can_approve_rebind: bool,
        can_generate_bast: bool,
        whatsapp_notify: bool,
        wa_jid: str | None,
    ) -> None:
        self.email = email
        self.display_name = display_name
        self.role = role
        self.scope_key = scope_key
        self.active = active
        self.can_approve_attendance = can_approve_attendance
        self.can_approve_rebind = can_approve_rebind
        self.can_generate_bast = can_generate_bast
        self.whatsapp_notify = whatsapp_notify
        self.wa_jid = wa_jid


class _InviteRow:
    __slots__ = ("active", "expires_at", "operator_email", "used_at")

    def __init__(
        self,
        operator_email: str,
        expires_at: datetime,
        used_at: datetime | None,
        active: bool,
    ) -> None:
        self.operator_email = operator_email
        self.expires_at = expires_at
        self.used_at = used_at
        self.active = active


class _SettingsRow:
    __slots__ = (
        "attendance_immediate",
        "deadline_reminder_days",
        "digest_enabled",
        "digest_hour",
        "rebind_immediate",
        "scope_key",
    )

    def __init__(
        self,
        scope_key: str,
        attendance_immediate: bool,
        rebind_immediate: bool,
        digest_enabled: bool,
        digest_hour: int,
        deadline_reminder_days: Sequence[int],
    ) -> None:
        self.scope_key = scope_key
        self.attendance_immediate = attendance_immediate
        self.rebind_immediate = rebind_immediate
        self.digest_enabled = digest_enabled
        self.digest_hour = digest_hour
        self.deadline_reminder_days = tuple(int(value) for value in deadline_reminder_days)


def _operator(row: _OperatorRow) -> WorkflowOperator:
    return WorkflowOperator(
        email=row.email,
        display_name=row.display_name,
        role=WorkflowRole(row.role),
        scope_key=row.scope_key,
        active=row.active,
        can_approve_attendance=row.can_approve_attendance,
        can_approve_rebind=row.can_approve_rebind,
        can_generate_bast=row.can_generate_bast,
        whatsapp_notify=row.whatsapp_notify,
        whatsapp_jid=row.wa_jid,
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_OPERATOR_SELECT: Final = """
    SELECT o.email,
           o.display_name,
           o.role,
           o.scope_key,
           o.active,
           o.can_approve_attendance,
           o.can_approve_rebind,
           o.can_generate_bast,
           o.whatsapp_notify,
           wi.wa_jid
    FROM workflow_operators o
    LEFT JOIN wa_operator_identity wi ON wi.operator_email = o.email
"""


@final
class WorkflowControlService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def list_operators(self) -> tuple[WorkflowOperator, ...]:
        return await run_sync(self._list_operators)

    async def operator(self, email: str) -> WorkflowOperator | None:
        return await run_sync(self._operator_by_email, email)

    async def resolve_jid(self, wa_jid: str) -> WorkflowOperator | None:
        return await run_sync(self._operator_by_jid, wa_jid)

    async def upsert_operator(
        self,
        *,
        email: str,
        display_name: str,
        role: WorkflowRole,
        scope_key: str,
        active: bool,
        can_approve_attendance: bool,
        can_approve_rebind: bool,
        can_generate_bast: bool,
        whatsapp_notify: bool,
        actor: str,
    ) -> WorkflowOperator:
        return await run_sync(
            self._upsert_operator,
            email,
            display_name,
            role,
            scope_key,
            active,
            can_approve_attendance,
            can_approve_rebind,
            can_generate_bast,
            whatsapp_notify,
            actor,
        )

    async def issue_whatsapp_invite(
        self, operator_email: str, actor: str
    ) -> WhatsAppInvite | None:
        return await run_sync(self._issue_whatsapp_invite, operator_email, actor)

    async def consume_whatsapp_invite(self, wa_jid: str, token: str) -> InviteResult:
        return await run_sync(self._consume_whatsapp_invite, wa_jid, token)

    async def unlink_whatsapp(self, operator_email: str) -> bool:
        return await run_sync(self._unlink_whatsapp, operator_email)

    async def notification_settings(self, scope_key: str = "default") -> NotificationSettings:
        return await run_sync(self._notification_settings, scope_key)

    async def save_notification_settings(
        self,
        *,
        scope_key: str,
        attendance_immediate: bool,
        rebind_immediate: bool,
        digest_enabled: bool,
        digest_hour: int,
        deadline_reminder_days: tuple[int, ...],
        actor: str,
    ) -> NotificationSettings:
        return await run_sync(
            self._save_notification_settings,
            scope_key,
            attendance_immediate,
            rebind_immediate,
            digest_enabled,
            digest_hour,
            deadline_reminder_days,
            actor,
        )

    def _list_operators(self) -> tuple[WorkflowOperator, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_OperatorRow)) as cursor,
            ):
                _ = cursor.execute(_OPERATOR_SELECT + " ORDER BY o.active DESC, o.role, o.email")
                return tuple(_operator(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="list_workflow_operators") from error

    def _operator_by_email(self, email: str) -> WorkflowOperator | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_OperatorRow)) as cursor,
            ):
                _ = cursor.execute(_OPERATOR_SELECT + " WHERE lower(o.email) = lower(%s)", (email,))
                row = cursor.fetchone()
                return None if row is None else _operator(row)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="get_workflow_operator") from error

    def _operator_by_jid(self, wa_jid: str) -> WorkflowOperator | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_OperatorRow)) as cursor,
            ):
                _ = cursor.execute(_OPERATOR_SELECT + " WHERE wi.wa_jid = %s", (wa_jid,))
                row = cursor.fetchone()
                return None if row is None else _operator(row)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="resolve_pmo_whatsapp") from error

    def _upsert_operator(  # noqa: PLR0913, PLR0917
        self,
        email: str,
        display_name: str,
        role: WorkflowRole,
        scope_key: str,
        active: bool,
        can_approve_attendance: bool,
        can_approve_rebind: bool,
        can_generate_bast: bool,
        whatsapp_notify: bool,
        actor: str,
    ) -> WorkflowOperator:
        normalized = email.strip().casefold()
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO workflow_operators (
                        email, display_name, role, scope_key, active,
                        can_approve_attendance, can_approve_rebind,
                        can_generate_bast, whatsapp_notify, created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (email) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        role = EXCLUDED.role,
                        scope_key = EXCLUDED.scope_key,
                        active = EXCLUDED.active,
                        can_approve_attendance = EXCLUDED.can_approve_attendance,
                        can_approve_rebind = EXCLUDED.can_approve_rebind,
                        can_generate_bast = EXCLUDED.can_generate_bast,
                        whatsapp_notify = EXCLUDED.whatsapp_notify,
                        updated_at = now()
                    """,
                    (
                        normalized,
                        display_name.strip() or normalized,
                        role.value,
                        scope_key.strip() or "default",
                        active,
                        can_approve_attendance,
                        can_approve_rebind,
                        can_generate_bast,
                        whatsapp_notify,
                        actor,
                    ),
                )
            operator = self._operator_by_email(normalized)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="upsert_workflow_operator") from error
        if operator is None:  # pragma: no cover - INSERT/SELECT invariant
            raise InfrastructureError(service="postgres", operation="reload_workflow_operator")
        return operator

    def _issue_whatsapp_invite(self, operator_email: str, actor: str) -> WhatsAppInvite | None:
        operator = self._operator_by_email(operator_email)
        if operator is None or not operator.active or operator.role is not WorkflowRole.PMO:
            return None
        token = _INVITE_PREFIX + secrets.token_urlsafe(24)
        expires_at = datetime.now(UTC) + _INVITE_TTL
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "UPDATE pmo_whatsapp_invites SET used_at = now() "
                    "WHERE operator_email = %s AND used_at IS NULL",
                    (operator.email,),
                )
                _ = cursor.execute(
                    """
                    INSERT INTO pmo_whatsapp_invites (
                        operator_email, token_hash, expires_at, issued_by
                    ) VALUES (%s,%s,%s,%s)
                    """,
                    (operator.email, _hash_token(token), expires_at, actor),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="issue_pmo_whatsapp_invite") from error
        return WhatsAppInvite(token=token, operator_email=operator.email, expires_at=expires_at)

    def _consume_whatsapp_invite(self, wa_jid: str, token: str) -> InviteResult:
        digest = _hash_token(token.strip())
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_InviteRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT i.operator_email, i.expires_at, i.used_at, o.active
                    FROM pmo_whatsapp_invites i
                    JOIN workflow_operators o ON o.email = i.operator_email
                    WHERE i.token_hash = %s
                    FOR UPDATE OF i, o
                    """,
                    (digest,),
                )
                invite = cursor.fetchone()
                if invite is None:
                    return InviteResult(InviteOutcome.INVALID)
                if invite.used_at is not None:
                    return InviteResult(InviteOutcome.USED)
                if invite.expires_at <= datetime.now(UTC):
                    return InviteResult(InviteOutcome.EXPIRED)
                if not invite.active:
                    return InviteResult(InviteOutcome.INACTIVE)
                _ = cursor.execute("SELECT 1 FROM wa_operator_identity WHERE wa_jid = %s", (wa_jid,))
                if cursor.fetchone() is not None:
                    return InviteResult(InviteOutcome.JID_ALREADY_LINKED)
                _ = cursor.execute(
                    "SELECT 1 FROM wa_operator_identity WHERE operator_email = %s",
                    (invite.operator_email,),
                )
                if cursor.fetchone() is not None:
                    return InviteResult(InviteOutcome.OPERATOR_ALREADY_LINKED)
                _ = cursor.execute(
                    "INSERT INTO wa_operator_identity (wa_jid, operator_email) VALUES (%s,%s)",
                    (wa_jid, invite.operator_email),
                )
                _ = cursor.execute(
                    """
                    UPDATE pmo_whatsapp_invites
                    SET used_at = now(), used_by_jid = %s
                    WHERE token_hash = %s
                    """,
                    (wa_jid, digest),
                )
            operator = self._operator_by_email(invite.operator_email)
            return InviteResult(InviteOutcome.LINKED, operator)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="consume_pmo_whatsapp_invite") from error

    def _unlink_whatsapp(self, operator_email: str) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "DELETE FROM wa_operator_identity WHERE lower(operator_email) = lower(%s)",
                    (operator_email,),
                )
                return cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="unlink_pmo_whatsapp") from error

    def _notification_settings(self, scope_key: str) -> NotificationSettings:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_SettingsRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT scope_key, attendance_immediate, rebind_immediate,
                           digest_enabled, digest_hour, deadline_reminder_days
                    FROM workflow_notification_settings
                    WHERE scope_key = %s
                    """,
                    (scope_key,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="workflow_notification_settings") from error
        if row is None:
            return NotificationSettings(scope_key, False, False, True, 9, (7, 3, 1))
        return NotificationSettings(
            row.scope_key,
            row.attendance_immediate,
            row.rebind_immediate,
            row.digest_enabled,
            row.digest_hour,
            row.deadline_reminder_days,
        )

    def _save_notification_settings(  # noqa: PLR0913, PLR0917
        self,
        scope_key: str,
        attendance_immediate: bool,
        rebind_immediate: bool,
        digest_enabled: bool,
        digest_hour: int,
        deadline_reminder_days: tuple[int, ...],
        actor: str,
    ) -> NotificationSettings:
        days = tuple(sorted({day for day in deadline_reminder_days if 0 <= day <= 31}, reverse=True))
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO workflow_notification_settings (
                        scope_key, attendance_immediate, rebind_immediate,
                        digest_enabled, digest_hour, deadline_reminder_days, updated_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (scope_key) DO UPDATE SET
                        attendance_immediate = EXCLUDED.attendance_immediate,
                        rebind_immediate = EXCLUDED.rebind_immediate,
                        digest_enabled = EXCLUDED.digest_enabled,
                        digest_hour = EXCLUDED.digest_hour,
                        deadline_reminder_days = EXCLUDED.deadline_reminder_days,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    """,
                    (
                        scope_key,
                        attendance_immediate,
                        rebind_immediate,
                        digest_enabled,
                        digest_hour,
                        list(days),
                        actor,
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="save_notification_settings") from error
        return NotificationSettings(
            scope_key,
            attendance_immediate,
            rebind_immediate,
            digest_enabled,
            digest_hour,
            days,
        )
