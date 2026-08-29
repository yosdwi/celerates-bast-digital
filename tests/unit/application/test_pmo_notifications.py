from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

import pytest

from digital_bast.application.pmo_notifications import (
    NotificationEnqueueCommand,
    NotificationOutboxItem,
    PmoNotificationService,
)
from digital_bast.application.talentops_followups import WhatsAppSendReceipt
from digital_bast.application.workflow_control import (
    NotificationSettings,
    WorkflowOperator,
    WorkflowRole,
)
from digital_bast.bot.attendance_resolution import (
    AttendanceResolution,
    ResolutionStatus,
    ResolutionType,
)
from digital_bast.bot.rebind import RebindRequest, RebindStatus

_NOW = datetime(2026, 8, 29, 2, 5, tzinfo=UTC)  # 09:05 Asia/Jakarta


def _operator(  # noqa: PLR0913 - compact permission fixture factory
    *,
    email: str = "pmo@example.com",
    active: bool = True,
    notify: bool = True,
    jid: str | None = "628111@s.whatsapp.net",
    attendance: bool = True,
    rebind: bool = True,
) -> WorkflowOperator:
    return WorkflowOperator(
        email=email,
        display_name="PMO Test",
        role=WorkflowRole.PMO,
        scope_key="default",
        active=active,
        can_approve_attendance=attendance,
        can_approve_rebind=rebind,
        can_generate_bast=True,
        whatsapp_notify=notify,
        whatsapp_jid=jid,
    )


def _attendance() -> AttendanceResolution:
    return AttendanceResolution(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        attendance_id=1,
        employee_id="employee-1",
        nrp="JIMT24002",
        full_name="Talent Test",
        work_date=date(2026, 8, 28),
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        absence_type=None,
        proposed_check_in=None,
        proposed_check_out=time(17, 23),
        status=ResolutionStatus.PENDING,
        evidence_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        requested_by_jid="628222@s.whatsapp.net",
        submitted_at=datetime(2026, 8, 28, 10, tzinfo=UTC),
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
    )


def _rebind() -> RebindRequest:
    return RebindRequest(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        employee_id="employee-2",
        nrp="JIMT24003",
        full_name="Talent Rebind",
        old_wa_jid="628333@s.whatsapp.net",
        new_wa_jid="628444@s.whatsapp.net",
        scope_key="default",
        status=RebindStatus.PENDING,
        requested_at=datetime(2026, 8, 28, 11, tzinfo=UTC),
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
    )


class Control:
    def __init__(
        self,
        settings: NotificationSettings,
        operators: tuple[WorkflowOperator, ...] = (_operator(),),
    ) -> None:
        self.settings = settings
        self.operators = operators

    async def list_operators(self) -> tuple[WorkflowOperator, ...]:
        return self.operators

    async def operator(self, email: str) -> WorkflowOperator | None:
        return next((item for item in self.operators if item.email == email), None)

    async def notification_settings(self, scope_key: str = "default") -> NotificationSettings:
        assert scope_key == "default"
        return self.settings


class AttendanceQueue:
    def __init__(self, items: tuple[AttendanceResolution, ...] = (_attendance(),)) -> None:
        self.items = items

    async def pending(self) -> tuple[AttendanceResolution, ...]:
        return self.items


class RebindQueue:
    def __init__(self, items: tuple[RebindRequest, ...] = (_rebind(),)) -> None:
        self.items = items

    async def pending(self, scope_key: str | None = None) -> tuple[RebindRequest, ...]:
        assert scope_key in (None, "default")
        return self.items


class Outbox:
    def __init__(self) -> None:
        self.items: dict[UUID, NotificationOutboxItem] = {}
        self.keys: set[tuple[str, str]] = set()

    async def enqueue(self, command: NotificationEnqueueCommand) -> bool:
        key = (command.operator_email, command.dedupe_key)
        if key in self.keys:
            return False
        self.keys.add(key)
        item_id = UUID(int=len(self.items) + 1)
        self.items[item_id] = NotificationOutboxItem(
            id=item_id,
            operator_email=command.operator_email,
            scope_key=command.scope_key,
            kind=command.kind,
            dedupe_key=command.dedupe_key,
            message=command.message,
            status="pending",
            attempts=0,
            next_attempt_at=command.available_at,
        )
        return True

    async def due(self, now: datetime, limit: int = 100) -> tuple[NotificationOutboxItem, ...]:
        return tuple(
            item
            for item in self.items.values()
            if item.status == "pending" and item.next_attempt_at <= now
        )[:limit]

    async def mark_sent(self, item_id: UUID, provider_message_id: str | None) -> None:
        _ = provider_message_id
        current = self.items[item_id]
        self.items[item_id] = replace(current, status="sent", attempts=current.attempts + 1)

    async def mark_failed(
        self,
        item_id: UUID,
        *,
        error_code: str,
        next_attempt_at: datetime,
        terminal: bool,
    ) -> None:
        _ = error_code
        current = self.items[item_id]
        self.items[item_id] = replace(
            current,
            status="dead" if terminal else "pending",
            attempts=current.attempts + 1,
            next_attempt_at=next_attempt_at,
        )


class Outbound:
    def __init__(self, receipts: list[WhatsAppSendReceipt] | None = None) -> None:
        self.receipts = receipts or [WhatsAppSendReceipt("sent", provider_message_id="wa-1")]
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        self.calls.append((jid, text, request_id))
        return self.receipts.pop(0)


def _settings(
    *,
    attendance_immediate: bool = False,
    rebind_immediate: bool = False,
    reminder_hour: int = 9,
    talent_days: tuple[int, ...] = (),
    pmo_days: tuple[int, ...] = (29,),
) -> NotificationSettings:
    return NotificationSettings(
        scope_key="default",
        attendance_immediate=attendance_immediate,
        rebind_immediate=rebind_immediate,
        reminder_hour=reminder_hour,
        talent_reminder_days=talent_days,
        pmo_reminder_days=pmo_days,
    )


def _service(  # noqa: PLR0913 - scenario factory keeps test setup readable
    settings: NotificationSettings,
    *,
    operators: tuple[WorkflowOperator, ...] = (_operator(),),
    attendance: tuple[AttendanceResolution, ...] = (_attendance(),),
    rebinds: tuple[RebindRequest, ...] = (_rebind(),),
    outbox: Outbox | None = None,
    outbound: Outbound | None = None,
) -> tuple[PmoNotificationService, Outbox, Outbound]:
    active_outbox = outbox or Outbox()
    active_outbound = outbound or Outbound()
    service = PmoNotificationService(
        "default",
        Control(settings, operators),
        AttendanceQueue(attendance),
        RebindQueue(rebinds),
        active_outbox,
        active_outbound,
    )
    return service, active_outbox, active_outbound


@pytest.mark.asyncio
async def test_configured_pmo_reminder_sends_once_on_calendar_date() -> None:
    service, _, outbound = _service(_settings())

    first = await service.run(_NOW)
    second = await service.run(_NOW + timedelta(minutes=15))

    assert first.enqueued == 1
    assert first.sent == 1
    assert second.enqueued == 0
    assert second.sent == 0
    assert len(outbound.calls) == 1
    assert "Attendance pending: 1" in outbound.calls[0][1]
    assert "Ganti nomor pending: 1" in outbound.calls[0][1]


@pytest.mark.asyncio
async def test_pmo_reminder_skips_other_dates_before_hour_and_empty_queue() -> None:
    wrong_date, _, wrong_date_outbound = _service(_settings(pmo_days=(28,)))
    before, _, before_outbound = _service(_settings(reminder_hour=10))
    empty, _, empty_outbound = _service(_settings(), attendance=(), rebinds=())

    wrong_date_result = await wrong_date.run(_NOW)
    before_result = await before.run(_NOW)
    empty_result = await empty.run(_NOW)

    assert wrong_date_result.enqueued == 0
    assert wrong_date_outbound.calls == []
    assert before_result.enqueued == 0
    assert before_outbound.calls == []
    assert empty_result.enqueued == 0
    assert empty_outbound.calls == []


@pytest.mark.asyncio
async def test_immediate_notices_follow_current_pmo_permissions() -> None:
    attendance_only = _operator(attendance=True, rebind=False)
    service, _, outbound = _service(
        _settings(attendance_immediate=True, rebind_immediate=True, pmo_days=()),
        operators=(attendance_only,),
    )

    result = await service.run(_NOW)

    assert result.enqueued == 1
    assert result.sent == 1
    assert len(outbound.calls) == 1
    assert "Attendance Pending" in outbound.calls[0][1]
    assert "Ganti Nomor" not in outbound.calls[0][1]


@pytest.mark.asyncio
async def test_bridge_failure_retries_on_later_worker_cycle_without_duplicate_enqueue() -> None:
    outbox = Outbox()
    outbound = Outbound(
        [
            WhatsAppSendReceipt("bridge_unavailable", error_code="bridge_unavailable"),
            WhatsAppSendReceipt("sent", provider_message_id="wa-2"),
        ]
    )
    service, _, _ = _service(
        _settings(attendance_immediate=True, pmo_days=()),
        rebinds=(),
        outbox=outbox,
        outbound=outbound,
    )

    first = await service.run(_NOW)
    too_early = await service.run(_NOW + timedelta(minutes=14))
    retried = await service.run(_NOW + timedelta(minutes=15))

    assert first.enqueued == 1
    assert first.retried == 1
    assert too_early.sent == 0
    assert retried.enqueued == 0
    assert retried.sent == 1
    assert len(outbound.calls) == 2


@pytest.mark.asyncio
async def test_unlinked_or_notification_disabled_pmo_is_not_targeted() -> None:
    service, _, outbound = _service(
        _settings(attendance_immediate=True),
        operators=(
            _operator(email="disabled@example.com", notify=False),
            _operator(email="unlinked@example.com", jid=None),
        ),
    )

    result = await service.run(_NOW)

    assert result.enqueued == 0
    assert outbound.calls == []
