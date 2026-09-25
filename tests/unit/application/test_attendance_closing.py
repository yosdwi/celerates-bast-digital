from dataclasses import replace
from datetime import date

from digital_bast.application.attendance_closing import (
    AttendanceClosingDayInput,
    AttendanceClosingReason,
    AttendanceClosingService,
    AttendanceClosingStatus,
    AttendanceCorrectionState,
    AttendanceScheduleState,
    AttendanceSourceState,
)


BASE_ROW = AttendanceClosingDayInput(
    attendance_id=1,
    attendance_date=date(2026, 9, 10),
    clock_in_local="08:00",
    clock_out_local="17:00",
)


def test_missing_clock_in_requires_talent_action() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[replace(BASE_ROW, clock_in_local=None)],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.needs_action is True
    assert result.waiting is False
    assert result.complete is False
    assert result.days[0].reason is AttendanceClosingReason.GAP_UNCOVERED
    assert result.days[0].missing_clock_in is True


def test_submitted_request_covering_full_gap_waits_for_approval() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                clock_out_local=None,
                correction_state=AttendanceCorrectionState.SUBMITTED,
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


def test_approved_correction_covering_full_gap_is_complete() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                clock_in_local=None,
                clock_out_local=None,
                correction_state=AttendanceCorrectionState.APPROVED,
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


def test_future_day_after_evaluated_through_is_ignored() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(BASE_ROW, attendance_id=1, attendance_date=date(2026, 9, 19)),
            replace(
                BASE_ROW,
                attendance_id=2,
                attendance_date=date(2026, 9, 21),
                clock_out_local=None,
            ),
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.COMPLETE
    assert [detail.attendance_id for detail in result.days] == [1]


def test_evidence_only_does_not_cover_missing_attendance() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                clock_in_local=None,
                correction_state=AttendanceCorrectionState.SUBMITTED,
                has_evidence=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.days[0].reason is AttendanceClosingReason.GAP_UNCOVERED


def test_partial_correction_does_not_cover_a_two_sided_gap() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                clock_in_local=None,
                clock_out_local=None,
                correction_state=AttendanceCorrectionState.SUBMITTED,
                correction_covers_clock_in=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION


def test_raw_complete_attendance_is_complete_without_request() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[BASE_ROW],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.COMPLETE
    assert result.days[0].reason is AttendanceClosingReason.RAW_COMPLETE


def test_uncovered_gap_has_precedence_over_waiting_submission() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                attendance_id=1,
                attendance_date=date(2026, 9, 10),
                clock_out_local=None,
                correction_state=AttendanceCorrectionState.SUBMITTED,
                correction_covers_clock_out=True,
            ),
            replace(
                BASE_ROW,
                attendance_id=2,
                attendance_date=date(2026, 9, 11),
                clock_in_local=None,
            ),
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION


def test_rejected_correction_returns_to_actionable() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                clock_out_local=None,
                correction_state=AttendanceCorrectionState.REJECTED,
                correction_covers_clock_out=True,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.days[0].reason is AttendanceClosingReason.CORRECTION_REJECTED


def test_scheduled_off_is_complete_without_clock_values() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                clock_in_local=None,
                clock_out_local=None,
                schedule_state=AttendanceScheduleState.OFF,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.COMPLETE
    assert result.days[0].reason is AttendanceClosingReason.SCHEDULED_OFF


def test_unavailable_source_never_becomes_complete() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[
            replace(
                BASE_ROW,
                attendance_id=None,
                clock_in_local=None,
                clock_out_local=None,
                schedule_state=AttendanceScheduleState.OFF,
                source_state=AttendanceSourceState.UNAVAILABLE,
            )
        ],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.days[0].attendance_id is None
    assert result.days[0].reason is AttendanceClosingReason.SOURCE_UNAVAILABLE


def test_empty_source_rows_never_become_complete() -> None:
    result = AttendanceClosingService().evaluate(
        employee_id="emp-101",
        rows=[],
        evaluated_through=date(2026, 9, 20),
    )

    assert result.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert result.days == ()
