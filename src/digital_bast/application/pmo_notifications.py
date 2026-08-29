"""Durable, low-noise PMO WhatsApp notifications.

The notification worker only surfaces actionable PMO work. Business authority
remains in the workflow services; this module reads pending queues, writes a
deduplicated outbox, and delivers through the existing WhatsApp bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, final

from digital_bast.application.workflow_control import WorkflowOperator, WorkflowRole
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from uuid import UUID

    from digital_bast.application.talentops_followups import WhatsAppSendReceipt
    from digital_bast.application.workflow_control import NotificationSettings
    from digital_bast.bot.attendance_resolution import AttendanceResolution
    from digital_bast.bot.rebind import RebindRequest

NotificationKind = Literal["attendance", "rebind", "digest"]
NotificationStatus = Literal["pending", "sent", "dead"]
_MAX_ATTEMPTS = 5
_RETRY_DELAYS = (
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
)


@dataclass(frozen=True, slots=True)
class NotificationOutboxItem:
    id: UUID
    operator_email: str
    scope_key: str
    kind: NotificationKind
    dedupe_key: str
    message: str
    status: NotificationStatus
    attempts: int
    next_attempt_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationRunSummary:
    enqueued: int = 0
    sent: int = 0
    retried: int = 0
    dead: int = 0


@dataclass(frozen=True, slots=True)
class NotificationEnqueueCommand:
    operator_email: str
    scope_key: str
    kind: NotificationKind
    dedupe_key: str
    message: str
    available_at: datetime


class WorkflowControlSource(Protocol):
    async def list_operators(self) -> tuple[WorkflowOperator, ...]: ...

    async def operator(self, email: str) -> WorkflowOperator | None: ...

    async def notification_settings(self, scope_key: str = "default") -> NotificationSettings: ...


class AttendanceQueueSource(Protocol):
    async def pending(self) -> tuple[AttendanceResolution, ...]: ...


class RebindQueueSource(Protocol):
    async def pending(self, scope_key: str | None = None) -> tuple[RebindRequest, ...]: ...


class NotificationOutbox(Protocol):
    async def enqueue(self, command: NotificationEnqueueCommand) -> bool: ...

    async def due(self, now: datetime, limit: int = 100) -> tuple[NotificationOutboxItem, ...]: ...

    async def mark_sent(self, item_id: UUID, provider_message_id: str | None) -> None: ...

    async def mark_failed(
        self,
        item_id: UUID,
        *,
        error_code: str,
        next_attempt_at: datetime,
        terminal: bool,
    ) -> None: ...


class NotificationOutboundGateway(Protocol):
    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt: ...


def _eligible_operator(operator: WorkflowOperator, scope_key: str) -> bool:
    return (
        operator.role is WorkflowRole.PMO
        and operator.scope_key == scope_key
        and operator.active
        and operator.whatsapp_notify
        and operator.whatsapp_jid is not None
    )


def _attendance_message(request: AttendanceResolution) -> str:
    return (
        "*Digital BAST — Attendance Pending*\n"
        f"{request.full_name} ({request.nrp}) · {request.work_date.isoformat()}\n"
        f"Request `{str(request.id)[:8]}` menunggu review.\n\n"
        "Balas `attendance` untuk buka queue."
    )


def _rebind_message(request: RebindRequest) -> str:
    return (
        "*Digital BAST — Ganti Nomor Pending*\n"
        f"{request.full_name} ({request.nrp})\n"
        f"Request `{str(request.id)[:8]}` menunggu review.\n\n"
        "Balas `rebind` untuk buka queue."
    )


def _pmo_reminder_message(attendance_count: int, rebind_count: int) -> str:
    return (
        "*Pengingat Digital BAST*\n"
        f"Attendance pending: {attendance_count}\n"
        f"Ganti nomor pending: {rebind_count}\n\n"
        "Balas `attendance` atau `rebind` untuk buka queue. "
        "Status lengkap tersedia di TalentOps."
    )


def _retry_at(now: datetime, next_attempt_number: int) -> datetime:
    index = min(max(next_attempt_number - 1, 0), len(_RETRY_DELAYS) - 1)
    return now + _RETRY_DELAYS[index]


@final
class PmoNotificationService:
    def __init__(  # noqa: PLR0913, PLR0917 - explicit ports make delivery side effects visible
        self,
        scope_key: str,
        control: WorkflowControlSource,
        attendance: AttendanceQueueSource,
        rebinds: RebindQueueSource,
        outbox: NotificationOutbox,
        outbound: NotificationOutboundGateway,
    ) -> None:
        self._scope_key = scope_key
        self._control = control
        self._attendance = attendance
        self._rebinds = rebinds
        self._outbox = outbox
        self._outbound = outbound

    async def run(self, now: datetime | None = None) -> NotificationRunSummary:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        settings = await self._control.notification_settings(self._scope_key)
        operators = tuple(
            operator
            for operator in await self._control.list_operators()
            if _eligible_operator(operator, self._scope_key)
        )
        local = current.astimezone(JAKARTA)
        scheduled_today = (
            local.day in settings.pmo_reminder_days and local.hour >= settings.reminder_hour
        )

        needs_attendance = any(operator.can_approve_attendance for operator in operators) and (
            settings.attendance_immediate or scheduled_today
        )
        needs_rebind = any(operator.can_approve_rebind for operator in operators) and (
            settings.rebind_immediate or scheduled_today
        )
        attendance = await self._attendance.pending() if needs_attendance else ()
        rebinds = await self._rebinds.pending(self._scope_key) if needs_rebind else ()

        enqueued = await self._enqueue(current, settings, operators, attendance, rebinds)
        sent, retried, dead = await self._dispatch(current)
        return NotificationRunSummary(enqueued=enqueued, sent=sent, retried=retried, dead=dead)

    async def _enqueue(
        self,
        now: datetime,
        settings: NotificationSettings,
        operators: tuple[WorkflowOperator, ...],
        attendance: tuple[AttendanceResolution, ...],
        rebinds: tuple[RebindRequest, ...],
    ) -> int:
        created = 0
        local = now.astimezone(JAKARTA)
        scheduled_today = (
            local.day in settings.pmo_reminder_days and local.hour >= settings.reminder_hour
        )
        for operator in operators:
            if settings.attendance_immediate and operator.can_approve_attendance:
                for request in attendance:
                    created += int(
                        await self._outbox.enqueue(
                            NotificationEnqueueCommand(
                                operator_email=operator.email,
                                scope_key=self._scope_key,
                                kind="attendance",
                                dedupe_key=f"attendance:{request.id}",
                                message=_attendance_message(request),
                                available_at=now,
                            )
                        )
                    )
            if settings.rebind_immediate and operator.can_approve_rebind:
                for request in rebinds:
                    created += int(
                        await self._outbox.enqueue(
                            NotificationEnqueueCommand(
                                operator_email=operator.email,
                                scope_key=self._scope_key,
                                kind="rebind",
                                dedupe_key=f"rebind:{request.id}",
                                message=_rebind_message(request),
                                available_at=now,
                            )
                        )
                    )

            if not scheduled_today:
                continue
            attendance_count = len(attendance) if operator.can_approve_attendance else 0
            rebind_count = len(rebinds) if operator.can_approve_rebind else 0
            if attendance_count + rebind_count == 0:
                continue
            created += int(
                await self._outbox.enqueue(
                    NotificationEnqueueCommand(
                        operator_email=operator.email,
                        scope_key=self._scope_key,
                        kind="digest",
                        dedupe_key=f"pmo-reminder:{local.date().isoformat()}",
                        message=_pmo_reminder_message(attendance_count, rebind_count),
                        available_at=now,
                    )
                )
            )
        return created

    async def _dispatch(self, now: datetime) -> tuple[int, int, int]:
        sent = 0
        retried = 0
        dead = 0
        for item in await self._outbox.due(now):
            operator = await self._control.operator(item.operator_email)
            if not self._can_receive(item, operator):
                await self._outbox.mark_failed(
                    item.id,
                    error_code="target_unavailable",
                    next_attempt_at=now,
                    terminal=True,
                )
                dead += 1
                continue
            if operator is None or operator.whatsapp_jid is None:
                await self._outbox.mark_failed(
                    item.id,
                    error_code="target_unavailable",
                    next_attempt_at=now,
                    terminal=True,
                )
                dead += 1
                continue
            receipt = await self._outbound.send(
                operator.whatsapp_jid,
                item.message,
                f"pmo-notification:{item.id}",
            )
            if receipt.status == "sent":
                await self._outbox.mark_sent(item.id, receipt.provider_message_id)
                sent += 1
                continue

            next_attempt = item.attempts + 1
            terminal = next_attempt >= _MAX_ATTEMPTS or receipt.error_code == "bridge_auth_failed"
            await self._outbox.mark_failed(
                item.id,
                error_code=receipt.error_code or receipt.status,
                next_attempt_at=_retry_at(now, next_attempt),
                terminal=terminal,
            )
            if terminal:
                dead += 1
            else:
                retried += 1
        return sent, retried, dead

    def _can_receive(
        self,
        item: NotificationOutboxItem,
        operator: WorkflowOperator | None,
    ) -> bool:
        if operator is None or not _eligible_operator(operator, self._scope_key):
            return False
        if item.kind == "attendance":
            return operator.can_approve_attendance
        if item.kind == "rebind":
            return operator.can_approve_rebind
        return operator.can_approve_attendance or operator.can_approve_rebind
