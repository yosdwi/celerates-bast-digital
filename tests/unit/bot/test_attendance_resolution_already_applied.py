from datetime import date, time

from digital_bast.bot.attendance_resolution import (
    ResolutionType,
    _already_applied,
    _AttendanceRow,
    _eligible,
)


def _row(check_in: time | None, check_out: time | None) -> _AttendanceRow:
    return _AttendanceRow(
        attendance_id=1, employee_id="E", work_date=date(2026, 9, 29), check_in=check_in, check_out=check_out
    )


def test_clock_in_filled_by_sync_with_the_proposed_value_is_not_a_conflict() -> None:
    row = _row(time(7, 0), time(17, 8))
    assert not _eligible(row, ResolutionType.MISSING_CLOCK_IN)
    assert _already_applied(row, ResolutionType.MISSING_CLOCK_IN, time(7, 0), None)


def test_clock_in_filled_with_a_different_value_still_conflicts() -> None:
    row = _row(time(7, 5), time(17, 8))
    assert not _already_applied(row, ResolutionType.MISSING_CLOCK_IN, time(7, 0), None)


def test_clock_out_filled_by_sync_with_the_proposed_value_is_not_a_conflict() -> None:
    row = _row(time(7, 30), time(16, 30))
    assert _already_applied(row, ResolutionType.MISSING_CLOCK_OUT, None, time(16, 30))


def test_absence_types_never_count_as_already_applied() -> None:
    row = _row(time(7, 30), time(16, 30))
    assert not _already_applied(row, ResolutionType.ABSENCE, None, None)
