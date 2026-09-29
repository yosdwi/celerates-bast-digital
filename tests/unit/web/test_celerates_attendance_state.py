from __future__ import annotations

from datetime import date

import pytest

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.payroll_read import PayrollDayView
from digital_bast.web.celerates_router import attendance_day_state

Reason = AttendanceClosingReason
Status = AttendanceClosingStatus


def day(  # noqa: PLR0913 - one projected day
    reason: AttendanceClosingReason,
    status: AttendanceClosingStatus,
    *,
    actionable: bool = False,
    off: bool = False,
    resolution_type: str | None = None,
    check_in: str | None = "08:00",
) -> PayrollDayView:
    return PayrollDayView(
        attendance_id=1,
        attendance_key="attendance:2026-09-01:E-1",
        work_date=date(2026, 9, 1),
        schedule_state=AttendanceScheduleState.OFF if off else AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in=check_in,
        raw_check_out="17:00",
        proposed_check_in=None,
        proposed_check_out=None,
        resolution_id=None if resolution_type is None else "r-1",
        resolution_status=None,
        resolution_type=resolution_type,
        absence_type="sakit" if resolution_type == "absence" else None,
        rejection_reason=None,
        has_evidence=False,
        status=status,
        reason=reason,
        talent_action_required=actionable,
    )


@pytest.mark.parametrize(
    ("view", "state"),
    [
        (day(Reason.RAW_COMPLETE, Status.COMPLETE), "complete"),
        (day(Reason.SCHEDULED_OFF, Status.COMPLETE, off=True, check_in=None), "not_required"),
        (day(Reason.GAP_UNCOVERED, Status.NEEDS_TALENT_ACTION, actionable=True), "needs_action"),
        (
            day(Reason.CORRECTION_REJECTED, Status.NEEDS_TALENT_ACTION, actionable=True),
            "needs_action",
        ),
        (
            day(Reason.SOURCE_UNAVAILABLE, Status.NEEDS_TALENT_ACTION, actionable=True),
            "needs_action",
        ),
        (
            day(Reason.GAP_COVERED_BY_SUBMITTED_REQUEST, Status.WAITING_SUBMITTED),
            "waiting_review",
        ),
        (
            day(
                Reason.GAP_COVERED_BY_APPROVED_CORRECTION,
                Status.COMPLETE,
                resolution_type="missing_clock_in",
            ),
            "complete",
        ),
        (
            day(
                Reason.GAP_COVERED_BY_APPROVED_CORRECTION,
                Status.COMPLETE,
                resolution_type="absence",
            ),
            "excused",
        ),
        (day(Reason.SOURCE_UNAVAILABLE, Status.NEEDS_TALENT_ACTION), "unverified"),
    ],
)
def test_projected_day_maps_to_the_contract_state(view: PayrollDayView, state: str) -> None:
    assert attendance_day_state(view) == state
