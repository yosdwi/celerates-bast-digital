from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

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
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA

_NOW = datetime(2026, 9, 19, 10, 0, tzinfo=JAKARTA)
_CYCLE = payroll_cycle(2026, 9)


def _talent() -> PayrollTalentView:
    day = PayrollDayView(
        attendance_id=10,
        attendance_key=f"attendance:{_CYCLE.period.start.isoformat()}",
        work_date=_CYCLE.period.start,
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
    return PayrollTalentView(
        employee_id="EMP-1",
        nrp="10001",
        name="Andi",
        role="Developer",
        status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
        evaluated_days=1,
        complete_days=0,
        waiting_days=0,
        actionable_days=1,
        unverified_days=0,
        days=(day,),
    )


class _Settings:
    async def load(self, scope_key: str = "default") -> PayrollClosingSettings:
        assert scope_key == "default"
        return PayrollClosingSettings(enabled=True)

    async def save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings:
        return settings

    async def mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings:
        assert scope_key == "default"
        return replace(PayrollClosingSettings(enabled=True), applied_version=version)


class _Payroll:
    async def overview(
        self,
        cycle: object,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
    ) -> PayrollOverview:
        _ = next_day_ready_hour
        assert cycle == _CYCLE
        assert now == _NOW
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=_CYCLE.period.start,
            summary=PayrollSummary(1, 0, 0, 1, 0),
            talents=(_talent(),),
        )


class _Identities:
    async def jid_for_employee(self, employee_id: str) -> str | None:
        assert employee_id == "EMP-1"
        return "628111@c.us"


class _Contexts:
    async def save(self, wa_jid: str, context: object) -> None:
        assert wa_jid == "628111@c.us"
        assert context is not None


class _Outbound:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        assert jid == "628111@c.us"
        assert text
        assert request_id.startswith("payroll:")
        self.calls += 1
        return WhatsAppSendReceipt(
            status="bridge_unavailable",
            error_code="delivery_outcome_unknown",
        )


class _Deliveries:
    def __init__(self) -> None:
        self.record: PayrollDeliveryRecord | None = None

    async def reserve(
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
        if self.record is not None:
            return PayrollDeliveryReservation(record=self.record, created=False)
        self.record = PayrollDeliveryRecord(
            id="delivery-1",
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
        return PayrollDeliveryReservation(record=self.record, created=True)

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        message: str,
        context_id: UUID,
    ) -> PayrollDeliveryRecord | None:
        assert self.record is not None
        assert self.record.idempotency_key == idempotency_key
        if self.record.state not in {
            PayrollDeliveryState.RESERVED,
            PayrollDeliveryState.FAILED_RETRYABLE,
        }:
            return None
        self.record = replace(
            self.record,
            message=message,
            context_id=context_id,
            state=PayrollDeliveryState.RESERVED,
            error_code=None,
        )
        return self.record

    async def claim(self, idempotency_key: str) -> PayrollDeliveryRecord | None:
        assert self.record is not None
        assert self.record.idempotency_key == idempotency_key
        if self.record.state is not PayrollDeliveryState.RESERVED:
            return None
        self.record = replace(
            self.record,
            state=PayrollDeliveryState.SENDING,
            attempt_count=self.record.attempt_count + 1,
        )
        return self.record

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        sent_at: datetime | None = None,
    ) -> PayrollDeliveryRecord | None:
        assert self.record is not None
        assert self.record.idempotency_key == idempotency_key
        self.record = replace(
            self.record,
            state=state,
            provider_message_id=provider_message_id,
            error_code=error_code,
            sent_at=sent_at,
        )
        return self.record

    async def list_cycle(
        self,
        *,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]:
        if self.record is None:
            return ()
        if self.record.scope_key != scope_key or self.record.cycle_id != cycle_id:
            return ()
        return (self.record,)


async def test_ambiguous_gateway_delivery_becomes_unknown_and_is_not_resent() -> None:
    outbound = _Outbound()
    deliveries = _Deliveries()
    service = PayrollTalentReminderService(
        "default",
        _Settings(),
        _Payroll(),
        _Identities(),
        _Contexts(),
        outbound,
        deliveries,
    )

    first = await service.run(now=_NOW)
    second = await service.run(now=_NOW)

    assert first.unknown == 1
    assert second.unknown == 1
    assert outbound.calls == 1
    assert deliveries.record is not None
    assert deliveries.record.state is PayrollDeliveryState.UNKNOWN
    assert deliveries.record.error_code == "delivery_outcome_unknown"
