from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

import pytest

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.attendance_review import AttendanceReviewEvidenceMetadata
from digital_bast.application.payroll_read import (
    PayrollDayView,
    PayrollOverview,
    PayrollSummary,
    PayrollTalentView,
)
from digital_bast.application.payroll_review import (
    PayrollReviewabilityReason,
    PayrollReviewDecision,
    PayrollReviewItemResultStatus,
    PayrollReviewService,
)
from digital_bast.bot.attendance_resolution import (
    AttendanceResolution,
    DecisionOutcome,
    DecisionResult,
    ResolutionStatus,
    ResolutionType,
)

_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_CYCLE = payroll_cycle(2026, 9)
_VALID_ID = UUID("00000000-0000-0000-0000-000000000101")
_STALE_ID = UUID("00000000-0000-0000-0000-000000000102")
_OUTSIDE_ID = UUID("00000000-0000-0000-0000-000000000103")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000201")


def _day(
    attendance_id: int,
    work_date: date,
    request_id: UUID,
    *,
    raw_out: str | None = None,
    waiting: bool = True,
) -> PayrollDayView:
    return PayrollDayView(
        attendance_id=attendance_id,
        attendance_key=f"ATT-{attendance_id}",
        work_date=work_date,
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in="07:30",
        raw_check_out=raw_out,
        proposed_check_in=None,
        proposed_check_out="17:40" if waiting else None,
        resolution_id=str(request_id),
        resolution_status="pending",
        resolution_type="missing_clock_out",
        absence_type=None,
        rejection_reason=None,
        has_evidence=True,
        status=(
            AttendanceClosingStatus.WAITING_SUBMITTED
            if waiting
            else AttendanceClosingStatus.COMPLETE
        ),
        reason=(
            AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST
            if waiting
            else AttendanceClosingReason.RAW_COMPLETE
        ),
        talent_action_required=False,
    )


def _overview() -> PayrollOverview:
    talent = PayrollTalentView(
        employee_id="EMP-1",
        nrp="10001",
        name="Andi",
        role="Developer",
        status=AttendanceClosingStatus.WAITING_SUBMITTED,
        evaluated_days=2,
        complete_days=1,
        waiting_days=1,
        actionable_days=0,
        unverified_days=0,
        days=(
            _day(11, date(2026, 9, 4), _VALID_ID),
            _day(12, date(2026, 9, 7), _STALE_ID, raw_out="17:55", waiting=False),
        ),
    )
    return PayrollOverview(
        cycle=_CYCLE,
        evaluated_through=date(2026, 9, 18),
        summary=PayrollSummary(1, 0, 1, 0, 0),
        talents=(talent,),
    )


def _request(
    request_id: UUID,
    attendance_id: int,
    work_date: date,
) -> AttendanceResolution:
    return AttendanceResolution(
        id=request_id,
        attendance_id=attendance_id,
        employee_id="EMP-1",
        nrp="10001",
        full_name="Andi",
        work_date=work_date,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        absence_type=None,
        proposed_check_in=None,
        proposed_check_out=time(17, 40),
        status=ResolutionStatus.PENDING,
        evidence_id=_EVIDENCE_ID,
        requested_by_jid="628123@s.whatsapp.net",
        submitted_at=_NOW,
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
    )


class _Payroll:
    async def overview(self, cycle: object, *, now: datetime) -> PayrollOverview:
        assert cycle == _CYCLE
        assert now == _NOW
        return _overview()


class _Evidence:
    async def metadata(self, request_id: UUID) -> AttendanceReviewEvidenceMetadata:
        return AttendanceReviewEvidenceMetadata(
            request_id=request_id,
            evidence_id=_EVIDENCE_ID,
            content_type="image/jpeg",
            byte_size=1234,
            caption="attendance",
            uploaded_at=_NOW,
        )


class _Resolutions:
    def __init__(self) -> None:
        self.decisions: list[UUID] = []

    async def pending(self) -> tuple[AttendanceResolution, ...]:
        return (
            _request(_VALID_ID, 11, date(2026, 9, 4)),
            _request(_STALE_ID, 12, date(2026, 9, 7)),
            _request(_OUTSIDE_ID, 13, date(2026, 8, 19)),
        )

    async def decide(
        self,
        request_id: UUID,
        reviewer: str,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> DecisionResult:
        assert reviewer == "pmo@example.com"
        assert approve is True
        assert rejection_reason is None
        self.decisions.append(request_id)
        return DecisionResult(DecisionOutcome.UPDATED, ResolutionStatus.APPROVED)


@pytest.mark.asyncio
async def test_queue_keeps_stale_pending_visible_but_not_reviewable() -> None:
    service = PayrollReviewService(_Payroll(), _Resolutions(), _Evidence())

    queue = await service.queue(_CYCLE, now=_NOW)

    assert [item.request_id for item in queue.items] == [_VALID_ID, _STALE_ID]
    valid, stale = queue.items
    assert valid.reviewable is True
    assert valid.reviewability_reason is None
    assert valid.raw_check_in == "07:30"
    assert valid.proposed_check_out == "17:40"
    assert valid.evidence_content_type == "image/jpeg"
    assert valid.evidence_byte_size == 1234
    assert stale.reviewable is False
    assert stale.reviewability_reason is PayrollReviewabilityReason.SOURCE_CHANGED
    assert stale.raw_check_out == "17:55"
    assert queue.summary.total == 2
    assert queue.summary.reviewable == 1
    assert queue.summary.stale == 1
    assert queue.summary.missing_clock_out == 2


@pytest.mark.asyncio
async def test_bulk_approve_is_partial_and_skips_stale_or_unknown_items() -> None:
    resolutions = _Resolutions()
    service = PayrollReviewService(_Payroll(), resolutions, _Evidence())
    unknown = UUID("00000000-0000-0000-0000-000000000999")

    result = await service.bulk_decide(
        _CYCLE,
        now=_NOW,
        request_ids=(_VALID_ID, _STALE_ID, unknown),
        decision=PayrollReviewDecision.APPROVE,
        reviewer="pmo@example.com",
    )

    assert resolutions.decisions == [_VALID_ID]
    assert result.requested == 3
    assert result.succeeded == 1
    assert result.skipped == 2
    assert result.failed == 0
    assert result.items[0].status is PayrollReviewItemResultStatus.SUCCEEDED
    assert result.items[0].outcome == "approved"
    assert result.items[1].outcome == "source_changed"
    assert result.items[2].outcome == "not_pending_in_cycle"


@pytest.mark.asyncio
async def test_reject_requires_reason_before_any_decision() -> None:
    resolutions = _Resolutions()
    service = PayrollReviewService(_Payroll(), resolutions, _Evidence())

    with pytest.raises(ValueError, match="rejection_reason"):
        await service.bulk_decide(
            _CYCLE,
            now=_NOW,
            request_ids=(_VALID_ID,),
            decision=PayrollReviewDecision.REJECT,
            reviewer="pmo@example.com",
            rejection_reason="   ",
        )

    assert resolutions.decisions == []
