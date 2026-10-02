from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from digital_bast.application.attendance_closing import AttendanceClosingStatus
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_digest import PayrollDigestService, PayrollFollowUpReason
from digital_bast.application.payroll_read import PayrollOverview, PayrollSummary, PayrollTalentView
from digital_bast.application.payroll_reminder_delivery import (
    PayrollDeliveryRecord,
    PayrollDeliveryState,
)
from digital_bast.domain.time import JAKARTA

_CYCLE = payroll_cycle(2026, 9)
_NOW = datetime(2026, 9, 19, 10, 0, tzinfo=JAKARTA)


def _talent(
    employee_id: str,
    *,
    actionable: int = 0,
    waiting: int = 0,
    unverified: int = 0,
) -> PayrollTalentView:
    if actionable:
        status = AttendanceClosingStatus.NEEDS_TALENT_ACTION
    elif waiting:
        status = AttendanceClosingStatus.WAITING_SUBMITTED
    else:
        status = AttendanceClosingStatus.COMPLETE
    return PayrollTalentView(
        employee_id=employee_id,
        nrp=f"NRP-{employee_id}",
        name=f"Talent {employee_id}",
        role="Developer",
        status=status,
        evaluated_days=1,
        complete_days=int(not actionable and not waiting and not unverified),
        waiting_days=waiting,
        actionable_days=actionable,
        unverified_days=unverified,
        days=(),
    )


def _delivery(
    employee_id: str,
    state: PayrollDeliveryState,
    *,
    minutes: int,
    responded: bool = False,
) -> PayrollDeliveryRecord:
    reserved_at = _NOW - timedelta(minutes=minutes)
    return PayrollDeliveryRecord(
        id=f"delivery-{employee_id}-{minutes}-{state.value}",
        idempotency_key=f"key-{employee_id}-{minutes}-{state.value}",
        employee_id=employee_id,
        message="Reminder",
        state=state,
        scope_key="default",
        cycle_id=_CYCLE.cycle_id,
        milestone="H-1",
        context_id=uuid4(),
        attempt_count=1,
        reserved_at=reserved_at,
        sent_at=reserved_at if state is PayrollDeliveryState.SENT else None,
        responded_at=reserved_at + timedelta(minutes=1) if responded else None,
        response_kind="attendance_action" if responded else None,
    )


class _Payroll:
    def __init__(self, talents: tuple[PayrollTalentView, ...]) -> None:
        self.talents = talents

    async def overview(
        self,
        cycle: object,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
    ) -> PayrollOverview:
        assert cycle == _CYCLE
        assert now == _NOW
        assert next_day_ready_hour == 7
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=_CYCLE.period.end,
            summary=PayrollSummary(0, 0, 0, 0, 0),
            talents=self.talents,
        )


class _Deliveries:
    def __init__(self, records: tuple[PayrollDeliveryRecord, ...]) -> None:
        self.records = records

    async def list_cycle(
        self,
        *,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]:
        assert scope_key == "default"
        assert cycle_id == _CYCLE.cycle_id
        return self.records


async def test_digest_uses_successful_delivery_and_response_correlation() -> None:
    talents = (
        _talent("A", actionable=1),
        _talent("B", actionable=1),
        _talent("C", actionable=1),
        _talent("D", waiting=1),
        _talent("E", unverified=1),
        _talent("F"),
    )
    deliveries = (
        _delivery("A", PayrollDeliveryState.SENT, minutes=20),
        _delivery("C", PayrollDeliveryState.SENT, minutes=30, responded=True),
        _delivery("C", PayrollDeliveryState.UNKNOWN, minutes=10),
        _delivery("OUTSIDE", PayrollDeliveryState.SENT, minutes=5),
    )
    digest = await PayrollDigestService(
        "default",
        _Payroll(talents),
        _Deliveries(deliveries),
    ).project(
        _CYCLE,
        now=_NOW,
        next_day_ready_hour=7,
        target_roles=("Developer",),
    )

    assert digest.summary.total_talents == 6
    assert digest.summary.complete == 1
    assert digest.summary.waiting_submitted == 1
    assert digest.summary.needs_talent_action == 3
    assert digest.summary.unverified == 1
    assert digest.summary.successful_reminder_deliveries == 2
    assert digest.summary.successfully_reminded_talents == 2
    assert digest.summary.unresponded_talents == 1
    assert digest.summary.actionable_not_reminded == 1
    assert digest.summary.delivery_unknown == 1
    assert [item.reason for item in digest.items] == [
        PayrollFollowUpReason.DELIVERY_UNKNOWN,
        PayrollFollowUpReason.UNRESPONDED,
        PayrollFollowUpReason.NOT_REMINDED,
        PayrollFollowUpReason.WAITING_REVIEW,
        PayrollFollowUpReason.SOURCE_UNVERIFIED,
    ]


async def test_digest_latest_successful_response_stops_unresponded() -> None:
    talents = (_talent("A", actionable=1),)
    deliveries = (
        _delivery("A", PayrollDeliveryState.SENT, minutes=30),
        _delivery("A", PayrollDeliveryState.SENT, minutes=10, responded=True),
    )
    digest = await PayrollDigestService(
        "default",
        _Payroll(talents),
        _Deliveries(deliveries),
    ).project(
        _CYCLE,
        now=_NOW,
        next_day_ready_hour=7,
    )

    assert digest.summary.successful_reminder_deliveries == 2
    assert digest.summary.successfully_reminded_talents == 1
    assert digest.summary.unresponded_talents == 0
    assert digest.items == ()
