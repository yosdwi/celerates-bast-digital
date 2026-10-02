from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_closing_settings import PayrollClosingSettings
from digital_bast.application.payroll_read import (
    PayrollDayView,
    PayrollOverview,
    PayrollSummary,
    PayrollTalentView,
)
from digital_bast.application.payroll_reminder_delivery import (
    PayrollDeliveryRecord,
    PayrollDeliveryReservation,
    PayrollDeliveryState,
)
from digital_bast.application.payroll_reminders import PayrollTalentReminderService
from digital_bast.application.talentops_followups import WhatsAppSendReceipt
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from uuid import UUID

    from digital_bast.bot.attendance_context import AttendanceReminderContext
    from digital_bast.domain.completion import DateRange

_NOW = datetime(2026, 9, 19, 10, 0, tzinfo=JAKARTA)
_CYCLE = payroll_cycle(2026, 9)


def _day(work_date: date) -> PayrollDayView:
    return PayrollDayView(
        attendance_id=10,
        attendance_key=f"attendance:{work_date.isoformat()}",
        work_date=work_date,
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in="07:30",
        raw_check_out=None,
        proposed_check_in=None,
        proposed_check_out=None,
        resolution_id=None,
        resolution_status=None,
        resolution_type=None,
        absence_type=None,
        rejection_reason=None,
        has_evidence=False,
        status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
        reason=AttendanceClosingReason.GAP_UNCOVERED,
        talent_action_required=True,
    )


def _talent(*, actionable: bool = True) -> PayrollTalentView:
    day = _day(_CYCLE.period.start) if actionable else replace(
        _day(_CYCLE.period.start),
        raw_check_out="17:00",
        status=AttendanceClosingStatus.COMPLETE,
        reason=AttendanceClosingReason.RAW_COMPLETE,
        talent_action_required=False,
    )
    return PayrollTalentView(
        employee_id="EMP-1" if actionable else "EMP-2",
        nrp="10001" if actionable else "10002",
        name="Andi" if actionable else "Budi",
        role="Developer",
        status=day.status,
        evaluated_days=1,
        complete_days=0 if actionable else 1,
        waiting_days=0,
        actionable_days=1 if actionable else 0,
        unverified_days=0,
        days=(day,),
    )


class _Settings:
    def __init__(self, value: PayrollClosingSettings) -> None:
        self.value = value
        self.applied: list[int] = []

    async def load(self, scope_key: str = "default") -> PayrollClosingSettings:
        assert scope_key == "default"
        return self.value

    async def save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings:
        self.value = settings
        return settings

    async def mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings:
        assert scope_key == "default"
        self.applied.append(version)
        self.value = replace(self.value, applied_version=version)
        return self.value


class _Payroll:
    def __init__(self) -> None:
        self.ready_hours: list[int] = []

    async def overview(
        self,
        cycle: object,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
    ) -> PayrollOverview:
        assert cycle == _CYCLE
        assert now == _NOW
        self.ready_hours.append(next_day_ready_hour)
        talents = (_talent(), _talent(actionable=False))
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=_CYCLE.period.start,
            summary=PayrollSummary(2, 1, 0, 1, 0),
            talents=talents,
        )


class _Identities:
    async def jid_for_employee(self, employee_id: str) -> str | None:
        return "628111@c.us" if employee_id == "EMP-1" else None


class _Contexts:
    def __init__(self) -> None:
        self.saved: list[tuple[str, AttendanceReminderContext]] = []

    async def save(self, wa_jid: str, context: AttendanceReminderContext) -> None:
        self.saved.append((wa_jid, context))


class _Outbound:
    def __init__(self, receipts: list[WhatsAppSendReceipt] | None = None) -> None:
        self.receipts = receipts or [
            WhatsAppSendReceipt(status="sent", provider_message_id="wa-1")
        ]
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        self.calls.append((jid, text, request_id))
        return self.receipts.pop(0)


class _Deliveries:
    def __init__(self) -> None:
        self.records: dict[str, PayrollDeliveryRecord] = {}
        self.attempts = 0

    async def reserve(  # noqa: PLR0913
        self,
        *,
        idempotency_key: str,
        employee_id: str,
        period: DateRange,
        message: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        context_id: UUID,
        created_by: str,
    ) -> PayrollDeliveryReservation:
        _ = (period, created_by)
        existing = self.records.get(idempotency_key)
        if existing is not None:
            return PayrollDeliveryReservation(record=existing, created=False)
        record = PayrollDeliveryRecord(
            id=f"fu-{len(self.records) + 1}",
            idempotency_key=idempotency_key,
            employee_id=employee_id,
            message=message,
            state=PayrollDeliveryState.RESERVED,
            scope_key=scope_key,
            cycle_id=cycle_id,
            milestone=milestone,
            context_id=context_id,
            attempt_count=0,
            reserved_at=_NOW,
        )
        self.records[idempotency_key] = record
        return PayrollDeliveryReservation(record=record, created=True)

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        message: str,
        context_id: UUID,
    ) -> PayrollDeliveryRecord | None:
        record = self.records[idempotency_key]
        retryable_states = {
            PayrollDeliveryState.RESERVED,
            PayrollDeliveryState.FAILED_RETRYABLE,
        }
        if record.state not in retryable_states:
            return None
        updated = replace(
            record,
            message=message,
            context_id=context_id,
            state=PayrollDeliveryState.RESERVED,
            error_code=None,
            reserved_at=_NOW,
        )
        self.records[idempotency_key] = updated
        return updated

    async def claim(self, idempotency_key: str) -> PayrollDeliveryRecord | None:
        record = self.records[idempotency_key]
        if record.state is not PayrollDeliveryState.RESERVED:
            return None
        self.attempts += 1
        updated = replace(
            record,
            state=PayrollDeliveryState.SENDING,
            attempt_count=record.attempt_count + 1,
        )
        self.records[idempotency_key] = updated
        return updated

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        sent_at: datetime | None = None,
    ) -> PayrollDeliveryRecord | None:
        record = self.records[idempotency_key]
        updated = replace(
            record,
            state=state,
            provider_message_id=provider_message_id,
            error_code=error_code,
            sent_at=sent_at if state is PayrollDeliveryState.SENT else record.sent_at,
        )
        self.records[idempotency_key] = updated
        return updated

    async def mark_attendance_response(
        self,
        *,
        context_id: UUID,
        employee_id: str,
        responded_at: datetime,
    ) -> bool:
        _ = (context_id, employee_id, responded_at)
        return True

    async def list_cycle(
        self,
        *,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]:
        return tuple(
            record
            for record in self.records.values()
            if record.scope_key == scope_key and record.cycle_id == cycle_id
        )


class _Gaps:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[date, ...]]] = []

    async def ensure_placeholder_rows(
        self, employee_id: str, work_dates: Sequence[date]
    ) -> None:
        self.calls.append((employee_id, tuple(work_dates)))


async def test_disabled_policy_preserves_no_payroll_dispatch() -> None:
    settings = _Settings(PayrollClosingSettings(enabled=False))
    outbound = _Outbound()
    service = PayrollTalentReminderService(
        "default",
        settings,
        _Payroll(),
        _Identities(),
        _Contexts(),
        outbound,
        _Deliveries(),
        _Gaps(),
    )

    result = await service.run(now=_NOW)

    assert result.enabled is False
    assert result.sent == 0
    assert outbound.calls == []


async def test_due_policy_sends_only_current_actionable_talent_and_persists_context() -> None:
    settings = _Settings(
        PayrollClosingSettings(
            enabled=True,
            next_day_ready_hour=7,
            desired_version=2,
            applied_version=1,
        )
    )
    payroll = _Payroll()
    contexts = _Contexts()
    outbound = _Outbound()
    deliveries = _Deliveries()
    service = PayrollTalentReminderService(
        "default",
        settings,
        payroll,
        _Identities(),
        contexts,
        outbound,
        deliveries,
        _Gaps(),
    )

    result = await service.run(now=_NOW)

    assert result.due_milestone == "H-1"
    assert result.evaluated_talents == 2
    assert result.actionable_talents == 1
    assert result.sent == 1
    assert settings.applied == [2]
    assert payroll.ready_hours == [7]
    assert len(contexts.saved) == 1
    assert contexts.saved[0][0] == "628111@c.us"
    assert len(outbound.calls) == 1
    assert outbound.calls[0][2].startswith("payroll:")
    assert len(outbound.calls[0][2]) == 72
    record = next(iter(deliveries.records.values()))
    assert ":H-1:EMP-1" in record.idempotency_key
    assert record.state is PayrollDeliveryState.SENT
    assert record.attempt_count == 1


async def test_retryable_failure_reuses_one_logical_delivery() -> None:
    settings = _Settings(PayrollClosingSettings(enabled=True))
    outbound = _Outbound(
        [
            WhatsAppSendReceipt(status="bridge_unavailable", error_code="bridge_down"),
            WhatsAppSendReceipt(status="sent", provider_message_id="wa-2"),
        ]
    )
    deliveries = _Deliveries()
    service = PayrollTalentReminderService(
        "default",
        settings,
        _Payroll(),
        _Identities(),
        _Contexts(),
        outbound,
        deliveries,
        _Gaps(),
    )

    first = await service.run(now=_NOW)
    second = await service.run(now=_NOW)

    assert first.retryable_failed == 1
    assert second.sent == 1
    assert len(deliveries.records) == 1
    assert deliveries.attempts == 2
    record = next(iter(deliveries.records.values()))
    assert record.state is PayrollDeliveryState.SENT
    assert record.attempt_count == 2
    assert outbound.calls[0][2] == outbound.calls[1][2]


async def test_manual_preview_and_send_revalidate_current_actionable_talent() -> None:
    outbound = _Outbound()
    deliveries = _Deliveries()
    contexts = _Contexts()
    service = PayrollTalentReminderService(
        "default",
        _Settings(PayrollClosingSettings(enabled=False)),
        _Payroll(),
        _Identities(),
        contexts,
        outbound,
        deliveries,
        _Gaps(),
    )

    preview = await service.preview_manual("EMP-1", _CYCLE, now=_NOW)
    request_id = uuid4()
    first = await service.send_manual("EMP-1", _CYCLE, request_id, now=_NOW)
    second = await service.send_manual("EMP-1", _CYCLE, request_id, now=_NOW)

    assert preview.eligible is True
    assert preview.message is not None
    assert "Andi" in preview.message
    assert first.sent is True
    assert first.outcome == "sent"
    assert second.sent is False
    assert second.outcome == "duplicate"
    assert len(outbound.calls) == 1
    assert outbound.calls[0][2].startswith("payroll:")
    assert len(outbound.calls[0][2]) == 72
    record = next(iter(deliveries.records.values()))
    assert record.idempotency_key.startswith("payroll-manual:default:")
    assert str(request_id) in record.idempotency_key
    assert len(contexts.saved) == 1


async def test_source_unavailable_day_backfills_placeholder_before_sending() -> None:
    """A day with no attendance row at all (SOURCE_UNAVAILABLE) must still be
    reminder-able -- the service backfills a placeholder row so
    compose_attendance_reminder gets a real attendance_key to anchor to.
    """
    missing_day = replace(
        _day(_CYCLE.period.start),
        attendance_id=None,
        attendance_key="",
        reason=AttendanceClosingReason.SOURCE_UNAVAILABLE,
    )
    backfilled_day = _day(_CYCLE.period.start)
    talent_before = replace(_talent(), days=(missing_day,))
    talent_after = replace(_talent(), days=(backfilled_day,))

    class _GapPayroll:
        def __init__(self) -> None:
            self.calls = 0

        async def overview(
            self,
            cycle: object,
            *,
            now: datetime,
            next_day_ready_hour: int = 6,
        ) -> PayrollOverview:
            assert cycle == _CYCLE
            assert now == _NOW
            self.calls += 1
            talent = talent_before if self.calls == 1 else talent_after
            return PayrollOverview(
                cycle=_CYCLE,
                evaluated_through=_CYCLE.period.start,
                summary=PayrollSummary(1, 0, 0, 1, 1),
                talents=(talent,),
            )

    payroll = _GapPayroll()
    gaps = _Gaps()
    outbound = _Outbound()
    deliveries = _Deliveries()
    service = PayrollTalentReminderService(
        "default",
        _Settings(PayrollClosingSettings(enabled=True)),
        payroll,
        _Identities(),
        _Contexts(),
        outbound,
        deliveries,
        gaps,
    )

    result = await service.send_manual("EMP-1", _CYCLE, uuid4(), now=_NOW)

    assert gaps.calls == [("EMP-1", (_CYCLE.period.start,))]
    assert payroll.calls == 2
    assert result.sent is True
    assert result.outcome == "sent"


async def test_manual_send_blocks_unknown_delivery_instead_of_blind_resend() -> None:
    outbound = _Outbound()
    deliveries = _Deliveries()
    deliveries.records["old"] = PayrollDeliveryRecord(
        id="old",
        idempotency_key="old",
        employee_id="EMP-1",
        message="old reminder",
        state=PayrollDeliveryState.UNKNOWN,
        scope_key="default",
        cycle_id=_CYCLE.cycle_id,
        milestone="H-1",
        context_id=uuid4(),
        attempt_count=1,
        reserved_at=_NOW,
    )
    service = PayrollTalentReminderService(
        "default",
        _Settings(PayrollClosingSettings(enabled=True)),
        _Payroll(),
        _Identities(),
        _Contexts(),
        outbound,
        deliveries,
        _Gaps(),
    )

    result = await service.send_manual("EMP-1", _CYCLE, uuid4(), now=_NOW)

    assert result.sent is False
    assert result.outcome == "unknown_blocked"
    assert outbound.calls == []
