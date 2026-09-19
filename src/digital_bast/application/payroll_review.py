"""Payroll PMO review projection and partial bulk decision orchestration.

The existing attendance resolution request remains the only approval lifecycle.
This module projects pending requests into a Payroll 21–20 review queue and
coordinates per-request decisions without mutating raw attendance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceSourceState,
)
from digital_bast.bot.attendance_resolution import (
    DecisionOutcome,
    ResolutionStatus,
    ResolutionType,
)
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date, datetime, time

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.attendance_review import AttendanceReviewEvidenceMetadata
    from digital_bast.application.payroll_read import PayrollOverview
    from digital_bast.bot.attendance_resolution import (
        AttendanceResolution,
        DecisionResult,
    )


class PayrollReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class PayrollReviewItemResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


class PayrollReviewabilityReason(StrEnum):
    TALENT_NOT_IN_CYCLE = "talent_not_in_cycle"
    ATTENDANCE_NOT_IN_PROJECTION = "attendance_not_in_projection"
    SOURCE_UNAVAILABLE = "source_unavailable"
    REQUEST_NOT_CURRENT = "request_not_current"
    SOURCE_CHANGED = "source_changed"
    EVIDENCE_NOT_FOUND = "evidence_not_found"


@dataclass(frozen=True, slots=True)
class PayrollReviewItem:
    request_id: UUID
    attendance_id: int
    employee_id: str
    nrp: str
    name: str
    role: str
    work_date: date
    resolution_type: ResolutionType
    raw_check_in: str | None
    raw_check_out: str | None
    proposed_check_in: str | None
    proposed_check_out: str | None
    absence_type: str | None
    evidence_id: UUID
    evidence_content_type: str | None
    evidence_byte_size: int | None
    evidence_caption: str
    evidence_uploaded_at: datetime | None
    submitted_at: datetime
    reviewable: bool
    reviewability_reason: PayrollReviewabilityReason | None


@dataclass(frozen=True, slots=True)
class PayrollReviewSummary:
    total: int
    reviewable: int
    stale: int
    missing_clock_in: int
    missing_clock_out: int
    missing_both_worked: int
    absence: int


@dataclass(frozen=True, slots=True)
class PayrollReviewQueue:
    cycle: PayrollCycle
    items: tuple[PayrollReviewItem, ...]
    summary: PayrollReviewSummary


@dataclass(frozen=True, slots=True)
class PayrollReviewDecisionItemResult:
    request_id: UUID
    status: PayrollReviewItemResultStatus
    outcome: str


@dataclass(frozen=True, slots=True)
class PayrollReviewDecisionResult:
    requested: int
    succeeded: int
    skipped: int
    failed: int
    items: tuple[PayrollReviewDecisionItemResult, ...]


class PayrollOverviewReader(Protocol):
    async def overview(self, cycle: PayrollCycle, *, now: datetime) -> PayrollOverview: ...


class AttendanceResolutionAuthority(Protocol):
    async def pending(self) -> tuple[AttendanceResolution, ...]: ...

    async def decide(
        self,
        request_id: UUID,
        reviewer: str,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> DecisionResult: ...


class AttendanceEvidenceReviewReader(Protocol):
    async def metadata(self, request_id: UUID) -> AttendanceReviewEvidenceMetadata | None: ...


def _clock(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _reviewability(
    request: AttendanceResolution,
    overview: PayrollOverview,
) -> tuple[bool, PayrollReviewabilityReason | None, str, str | None, str | None]:
    talent = next(
        (item for item in overview.talents if item.employee_id == request.employee_id),
        None,
    )
    if talent is None:
        return False, PayrollReviewabilityReason.TALENT_NOT_IN_CYCLE, "", None, None
    day = next(
        (
            item
            for item in talent.days
            if item.attendance_id == request.attendance_id
            and item.work_date == request.work_date
        ),
        None,
    )
    if day is None:
        return (
            False,
            PayrollReviewabilityReason.ATTENDANCE_NOT_IN_PROJECTION,
            talent.role,
            None,
            None,
        )
    if day.source_state is AttendanceSourceState.UNAVAILABLE:
        return (
            False,
            PayrollReviewabilityReason.SOURCE_UNAVAILABLE,
            talent.role,
            day.raw_check_in,
            day.raw_check_out,
        )
    if day.resolution_id != str(request.id) or day.resolution_status != ResolutionStatus.PENDING.value:
        return (
            False,
            PayrollReviewabilityReason.REQUEST_NOT_CURRENT,
            talent.role,
            day.raw_check_in,
            day.raw_check_out,
        )
    if (
        day.status is not AttendanceClosingStatus.WAITING_SUBMITTED
        or day.reason is not AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST
    ):
        return (
            False,
            PayrollReviewabilityReason.SOURCE_CHANGED,
            talent.role,
            day.raw_check_in,
            day.raw_check_out,
        )
    return True, None, talent.role, day.raw_check_in, day.raw_check_out


def _summary(items: tuple[PayrollReviewItem, ...]) -> PayrollReviewSummary:
    return PayrollReviewSummary(
        total=len(items),
        reviewable=sum(item.reviewable for item in items),
        stale=sum(not item.reviewable for item in items),
        missing_clock_in=sum(
            item.resolution_type is ResolutionType.MISSING_CLOCK_IN for item in items
        ),
        missing_clock_out=sum(
            item.resolution_type is ResolutionType.MISSING_CLOCK_OUT for item in items
        ),
        missing_both_worked=sum(
            item.resolution_type is ResolutionType.MISSING_BOTH_WORKED for item in items
        ),
        absence=sum(item.resolution_type is ResolutionType.ABSENCE for item in items),
    )


class PayrollReviewService:
    def __init__(
        self,
        payroll: PayrollOverviewReader,
        resolutions: AttendanceResolutionAuthority,
        evidence: AttendanceEvidenceReviewReader,
    ) -> None:
        self._payroll = payroll
        self._resolutions = resolutions
        self._evidence = evidence

    async def queue(self, cycle: PayrollCycle, *, now: datetime) -> PayrollReviewQueue:
        overview = await self._payroll.overview(cycle, now=now)
        pending = await self._resolutions.pending()
        items: list[PayrollReviewItem] = []
        for request in pending:
            if not cycle.period.start <= request.work_date <= cycle.period.end:
                continue
            reviewable, reason, role, raw_in, raw_out = _reviewability(request, overview)
            evidence = await self._evidence.metadata(request.id)
            if evidence is None:
                reviewable = False
                reason = PayrollReviewabilityReason.EVIDENCE_NOT_FOUND
            items.append(
                PayrollReviewItem(
                    request_id=request.id,
                    attendance_id=request.attendance_id,
                    employee_id=request.employee_id,
                    nrp=request.nrp,
                    name=request.full_name,
                    role=role,
                    work_date=request.work_date,
                    resolution_type=request.resolution_type,
                    raw_check_in=raw_in,
                    raw_check_out=raw_out,
                    proposed_check_in=_clock(request.proposed_check_in),
                    proposed_check_out=_clock(request.proposed_check_out),
                    absence_type=(
                        request.absence_type.value if request.absence_type is not None else None
                    ),
                    evidence_id=request.evidence_id,
                    evidence_content_type=(evidence.content_type if evidence is not None else None),
                    evidence_byte_size=(evidence.byte_size if evidence is not None else None),
                    evidence_caption=(evidence.caption if evidence is not None else ""),
                    evidence_uploaded_at=(evidence.uploaded_at if evidence is not None else None),
                    submitted_at=request.submitted_at,
                    reviewable=reviewable,
                    reviewability_reason=reason,
                )
            )
        queue_items = tuple(items)
        return PayrollReviewQueue(cycle, queue_items, _summary(queue_items))

    async def bulk_decide(  # noqa: PLR0913
        self,
        cycle: PayrollCycle,
        *,
        now: datetime,
        request_ids: tuple[UUID, ...],
        decision: PayrollReviewDecision,
        reviewer: str,
        rejection_reason: str | None = None,
    ) -> PayrollReviewDecisionResult:
        ordered_ids = tuple(dict.fromkeys(request_ids))
        if not ordered_ids:
            return PayrollReviewDecisionResult(0, 0, 0, 0, ())
        if len(ordered_ids) > 100:
            raise ValueError("Payroll review batch cannot exceed 100 requests")
        normalized_reason = (rejection_reason or "").strip()
        if decision is PayrollReviewDecision.REJECT and not normalized_reason:
            raise ValueError("rejection_reason is required for reject")

        queue = await self.queue(cycle, now=now)
        by_id = {item.request_id: item for item in queue.items}
        results: list[PayrollReviewDecisionItemResult] = []
        approve = decision is PayrollReviewDecision.APPROVE
        for request_id in ordered_ids:
            current = by_id.get(request_id)
            if current is None:
                results.append(
                    PayrollReviewDecisionItemResult(
                        request_id,
                        PayrollReviewItemResultStatus.SKIPPED,
                        "not_pending_in_cycle",
                    )
                )
                continue
            if not current.reviewable:
                results.append(
                    PayrollReviewDecisionItemResult(
                        request_id,
                        PayrollReviewItemResultStatus.SKIPPED,
                        current.reviewability_reason.value
                        if current.reviewability_reason is not None
                        else "not_reviewable",
                    )
                )
                continue
            try:
                decided = await self._resolutions.decide(
                    request_id,
                    reviewer,
                    approve=approve,
                    rejection_reason=normalized_reason or None,
                )
            except InfrastructureError:
                results.append(
                    PayrollReviewDecisionItemResult(
                        request_id,
                        PayrollReviewItemResultStatus.FAILED,
                        "infrastructure_error",
                    )
                )
                continue
            if decided.outcome is DecisionOutcome.UPDATED:
                expected_status = (
                    ResolutionStatus.APPROVED if approve else ResolutionStatus.REJECTED
                )
                outcome = (
                    expected_status.value
                    if decided.status is expected_status
                    else "unexpected_status"
                )
                item_status = (
                    PayrollReviewItemResultStatus.SUCCEEDED
                    if decided.status is expected_status
                    else PayrollReviewItemResultStatus.FAILED
                )
            elif decided.outcome in {
                DecisionOutcome.NOT_FOUND,
                DecisionOutcome.ALREADY_RESOLVED,
                DecisionOutcome.SOURCE_CHANGED,
            }:
                item_status = PayrollReviewItemResultStatus.SKIPPED
                outcome = decided.outcome.value
            else:
                item_status = PayrollReviewItemResultStatus.FAILED
                outcome = decided.outcome.value
            results.append(PayrollReviewDecisionItemResult(request_id, item_status, outcome))

        items = tuple(results)
        return PayrollReviewDecisionResult(
            requested=len(items),
            succeeded=sum(item.status is PayrollReviewItemResultStatus.SUCCEEDED for item in items),
            skipped=sum(item.status is PayrollReviewItemResultStatus.SKIPPED for item in items),
            failed=sum(item.status is PayrollReviewItemResultStatus.FAILED for item in items),
            items=items,
        )
