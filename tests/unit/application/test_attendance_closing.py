from datetime import date

from digital_bast.application.attendance_closing import (
    AttendanceClosingDayInput,
    AttendanceClosingReason,
    AttendanceClosingService,
    AttendanceClosingStatus,
)


def _row(
    *,
    attendance_id: int = 1,
    attendance_date: date = date(2026, 9, 10),
    clock_in_local: str | None = "08:00",
    clock_out_local: str | None = "17:00",
    request_submitted: bool = False,
    request_approved: bool = False,
    correction_covers_clock_in: bool = False,
    correction_covers_clock_out: bool = False,
    has_evidence: bool = False,
) -> AttendanceClosingDayInput:
    return AttendanceClosingDayInput(
        attendance_id=attendance_id,
        attendance_date=attendance_date,
        clock_in_local=clock_in_local,
        clock_out_local=clock_out_local,
        request_submitted=request_submitted,
        request_approved=request_approved,
        correction_covers_clock_in=correction_covers_clock_in,
        correction_covers_clock_out=correction_covers_clock_out,
        has_evidence=has_evidence,
    )


def test_missing_clock_in_requires_talent_action():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[_row(clock_in_local=None)],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.needs_action is True
    assert result.waiting is False
    assert result.complete is False
    assert result.days[0].reason is AttendanceClosingReason.GAP_UNCOVERED
    assert result.days[0].missing_clock_in is True


def test_submitted_request_covering_full_gap_waits_for_approval():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[
            _row(
                clock_out_local=None,
                request_submitted=True,
                correction_covers_clock_out=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.WAITING_SUBMITTED
    assert result.waiting is True
    assert (
        result.days[0].reason
        is AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST
    )


def test_approved_correction_covering_full_gap_is_complete():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[
            _row(
                clock_in_local=None,
                clock_out_local=None,
                request_approved=True,
                correction_covers_clock_in=True,
                correction_covers_clock_out=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.COMPLETE
    assert result.complete is True
    assert (
        result.days[0].reason
        is AttendanceClosingReason.GAP_COVERED_BY_APPROVED_CORRECTION
    )


def test_future_day_after_evaluated_through_is_ignored():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[
            _row(attendance_id=1, attendance_date=date(2026, 9, 19)),
            _row(
                attendance_id=2,
                attendance_date=date(2026, 9, 21),
                clock_out_local=None,
            ),
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.COMPLETE
    assert [detail.attendance_id for detail in result.days] == [1]


def test_evidence_only_does_not_cover_missing_attendance():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[
            _row(
                clock_in_local=None,
                request_submitted=True,
                has_evidence=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.days[0].reason is AttendanceClosingReason.GAP_UNCOVERED


def test_partial_correction_does_not_cover_a_two_sided_gap():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[
            _row(
                clock_in_local=None,
                clock_out_local=None,
                request_submitted=True,
                correction_covers_clock_in=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION


def test_raw_complete_attendance_is_complete_without_request():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[_row()],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.COMPLETE
    assert result.days[0].reason is AttendanceClosingReason.RAW_COMPLETE


def test_uncovered_gap_has_precedence_over_waiting_submission():
    result = AttendanceClosingService().evaluate(
        employee_id=101,
        rows=[
            _row(
                attendance_id=1,
                attendance_date=date(2026, 9, 10),
                clock_out_local=None,
                request_submitted=True,
                correction_covers_clock_out=True,
            ),
            _row(
                attendance_id=2,
                attendance_date=date(2026, 9, 11),
                clock_in_local=None,
            ),
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
