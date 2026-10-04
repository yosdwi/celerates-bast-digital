from __future__ import annotations

from datetime import date

import pytest

from digital_bast.domain.completion import (
    CheckState,
    DateRange,
    EmployeeFacts,
    TimesheetFact,
    evaluate_employee,
)
from digital_bast.domain.timesheets import is_off_shift

DAY = date(2026, 9, 22)
PERIOD = DateRange(DAY, DAY)


def _facts(timesheet: TimesheetFact | None) -> EmployeeFacts:
    return EmployeeFacts(
        employee_id="7",
        name="Gading",
        off_days=frozenset({DAY}),  # the schedule says Libur
        attendance=(),
        timesheets=() if timesheet is None else (timesheet,),
        tasks=(),
        evidence_available=True,
        attendance_available=True,
    )


@pytest.mark.parametrize(
    ("shift", "expected"),
    [
        ("Libur", True),
        ("libur", True),
        ("  LIBUR  ", True),
        ("SHIFT 1", False),
        ("Sakit", False),
        ("Tugas Site", False),
        ("", False),
        (None, False),
    ],
)
def test_only_a_libur_shift_is_a_day_off(shift: str | None, expected: bool) -> None:
    assert is_off_shift(shift) is expected


def test_off_day_whose_timesheet_still_says_working_shift_is_flagged() -> None:
    # The Gading case: the sheet row was generated as "SHIFT 1" and never changed when the
    # schedule became Libur. It used to pass because the remark was merely non-empty.
    result = evaluate_employee(_facts(TimesheetFact(DAY, "SHIFT 1", marked_off=False)), PERIOD)

    assert result.timesheet.state is CheckState.INCOMPLETE
    (issue,) = result.timesheet.issues
    assert "masih tercatat hari kerja (SHIFT 1)" in issue
    assert "Libur" in issue


def test_off_day_with_a_proper_off_row_is_fine() -> None:
    result = evaluate_employee(_facts(TimesheetFact(DAY, "Libur", marked_off=True)), PERIOD)
    assert result.timesheet.state is CheckState.COMPLETE


def test_a_caller_that_does_not_know_the_flag_never_gets_the_new_finding() -> None:
    # Default marked_off=True: older callers and fixtures are unaffected.
    result = evaluate_employee(_facts(TimesheetFact(DAY, "SHIFT 1")), PERIOD)
    assert result.timesheet.state is CheckState.COMPLETE


def test_existing_findings_are_unchanged() -> None:
    missing = evaluate_employee(_facts(None), PERIOD)
    assert missing.timesheet.issues == ("22 Sep — Timesheet untuk jadwal OFF belum tersedia.",) or (
        "Timesheet untuk jadwal OFF belum tersedia" in missing.timesheet.issues[0]
    )
    blank = evaluate_employee(_facts(TimesheetFact(DAY, "  ", marked_off=False)), PERIOD)
    assert "Keterangan OFF pada Timesheet belum terisi" in blank.timesheet.issues[0]
