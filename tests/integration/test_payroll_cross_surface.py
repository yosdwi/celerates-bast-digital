from __future__ import annotations

from datetime import datetime, time

import pytest

from digital_bast.application.attendance_closing import (
    AttendanceClosingDayInput,
    AttendanceClosingService,
    AttendanceClosingStatus,
    AttendanceCorrectionState,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.attendance_review import AttendanceReviewService
from digital_bast.application.payroll_read import (
    PayrollDayView,
    PayrollOverview,
    PayrollSummary,
    PayrollTalentView,
)
from digital_bast.application.payroll_review import PayrollReviewDecision, PayrollReviewService
from digital_bast.bot.attendance_resolution import AttendanceResolutionService, ResolutionType
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.payroll_attendance import PostgresPayrollAttendanceReader
from digital_bast.web.postgres_backend import PostgresWebBackend
from tests.integration.test_attendance_resolution import database_dsn, seed_attendance

_CYCLE = payroll_cycle(2026, 9)
_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=JAKARTA)


def _clock(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _correction_state(value: str | None) -> AttendanceCorrectionState:
    return {
        "pending": AttendanceCorrectionState.SUBMITTED,
        "approved": AttendanceCorrectionState.APPROVED,
        "rejected": AttendanceCorrectionState.REJECTED,
    }.get(value, AttendanceCorrectionState.NONE)


def _coverage(resolution_type: str | None) -> tuple[bool, bool]:
    if resolution_type == "missing_clock_in":
        return True, False
    if resolution_type == "missing_clock_out":
        return False, True
    if resolution_type in {"missing_both_worked", "absence"}:
        return True, True
    return False, False


class _SingleTalentOverview:
    def __init__(
        self,
        dsn: str,
        *,
        employee_id: str,
        nrp: str,
        name: str,
        role: str = "Developer",
    ) -> None:
        self._reader = PostgresPayrollAttendanceReader(dsn)
        self._employee_id = employee_id
        self._nrp = nrp
        self._name = name
        self._role = role
        self._closing = AttendanceClosingService()

    async def overview(self, cycle: object, *, now: datetime) -> PayrollOverview:
        assert cycle == _CYCLE
        assert now == _NOW
        records = await self._reader.load(_CYCLE.period)
        record = next(item for item in records if item.employee_id == self._employee_id)
        covers_in, covers_out = _coverage(record.resolution_type)
        closing = self._closing.evaluate(
            employee_id=self._employee_id,
            rows=(
                AttendanceClosingDayInput(
                    attendance_id=record.attendance_id,
                    attendance_date=record.work_date,
                    clock_in_local=_clock(record.check_in),
                    clock_out_local=_clock(record.check_out),
                    correction_state=_correction_state(record.resolution_status),
                    correction_covers_clock_in=covers_in,
                    correction_covers_clock_out=covers_out,
                    schedule_state=AttendanceScheduleState.WORKING,
                    source_state=AttendanceSourceState.AVAILABLE,
                    has_evidence=record.has_evidence,
                ),
            ),
            evaluated_through=record.work_date,
        )
        detail = closing.days[0]
        day = PayrollDayView(
            attendance_id=record.attendance_id,
            attendance_key=record.attendance_key,
            work_date=record.work_date,
            schedule_state=AttendanceScheduleState.WORKING,
            source_state=AttendanceSourceState.AVAILABLE,
            raw_check_in=_clock(record.check_in),
            raw_check_out=_clock(record.check_out),
            proposed_check_in=_clock(record.proposed_check_in),
            proposed_check_out=_clock(record.proposed_check_out),
            resolution_id=record.resolution_id,
            resolution_status=record.resolution_status,
            resolution_type=record.resolution_type,
            absence_type=record.absence_type,
            rejection_reason=record.rejection_reason,
            has_evidence=record.has_evidence,
            status=detail.status,
            reason=detail.reason,
            talent_action_required=(detail.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION),
        )
        complete = int(detail.status is AttendanceClosingStatus.COMPLETE)
        waiting = int(detail.status is AttendanceClosingStatus.WAITING_SUBMITTED)
        actionable = int(detail.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION)
        talent = PayrollTalentView(
            employee_id=self._employee_id,
            nrp=self._nrp,
            name=self._name,
            role=self._role,
            status=detail.status,
            evaluated_days=1,
            complete_days=complete,
            waiting_days=waiting,
            actionable_days=actionable,
            unverified_days=0,
            days=(day,),
        )
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=record.work_date,
            summary=PayrollSummary(
                total_talents=1,
                complete=complete,
                waiting_submitted=waiting,
                needs_talent_action=actionable,
                unverified=0,
            ),
            talents=(talent,),
        )


@pytest.mark.asyncio
async def test_whatsapp_submission_pmo_approval_closing_and_legacy_export_share_truth(
    database_dsn: str,
) -> None:
    employee_id, nrp, full_name, attendance_key = seed_attendance(
        database_dsn,
        check_in=time(8, 3),
        check_out=None,
    )
    resolutions = AttendanceResolutionService(database_dsn)
    submitted = await resolutions.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.MISSING_CLOCK_OUT,
        proposed_check_out=time(17, 23),
    )
    assert submitted.request_id is not None

    overview = _SingleTalentOverview(
        database_dsn,
        employee_id=employee_id,
        nrp=nrp,
        name=full_name,
    )
    review = PayrollReviewService(
        overview,
        resolutions,
        AttendanceReviewService(database_dsn),
    )

    queue = await review.queue(_CYCLE, now=_NOW)
    assert queue.summary.total == 1
    assert queue.summary.reviewable == 1
    assert queue.items[0].request_id == submitted.request_id
    assert queue.items[0].raw_check_out is None
    assert queue.items[0].proposed_check_out == "17:23"
    assert (await overview.overview(_CYCLE, now=_NOW)).talents[0].status is AttendanceClosingStatus.WAITING_SUBMITTED

    decision = await review.bulk_decide(
        _CYCLE,
        now=_NOW,
        request_ids=(submitted.request_id,),
        decision=PayrollReviewDecision.APPROVE,
        reviewer="pmo@example.com",
    )
    assert decision.succeeded == 1

    projected = await overview.overview(_CYCLE, now=_NOW)
    assert projected.talents[0].status is AttendanceClosingStatus.COMPLETE
    assert projected.talents[0].days[0].raw_check_out is None
    assert projected.talents[0].days[0].proposed_check_out == "17:23"

    content, rows = await PostgresWebBackend(database_dsn).attendance_legacy(
        "Developer",
        _CYCLE.period.start,
        _CYCLE.period.end,
        full_name,
    )
    assert rows == 1
    assert "17:23" in content


@pytest.mark.asyncio
async def test_pmo_rejection_returns_closing_item_to_talent_action(database_dsn: str) -> None:
    employee_id, nrp, full_name, attendance_key = seed_attendance(
        database_dsn,
        check_in=None,
        check_out=time(17, 12),
    )
    resolutions = AttendanceResolutionService(database_dsn)
    submitted = await resolutions.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.MISSING_CLOCK_IN,
        proposed_check_in=time(7, 41),
    )
    assert submitted.request_id is not None
    overview = _SingleTalentOverview(
        database_dsn,
        employee_id=employee_id,
        nrp=nrp,
        name=full_name,
    )
    review = PayrollReviewService(
        overview,
        resolutions,
        AttendanceReviewService(database_dsn),
    )

    decision = await review.bulk_decide(
        _CYCLE,
        now=_NOW,
        request_ids=(submitted.request_id,),
        decision=PayrollReviewDecision.REJECT,
        reviewer="pmo@example.com",
        rejection_reason="Evidence tidak sesuai",
    )
    assert decision.succeeded == 1

    projected = await overview.overview(_CYCLE, now=_NOW)
    assert projected.talents[0].status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert projected.talents[0].days[0].rejection_reason == "Evidence tidak sesuai"
