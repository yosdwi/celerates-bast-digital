from __future__ import annotations

from datetime import UTC, date, datetime

from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.web.bast_assembler import _AttendanceRow, _timesheet_report, _TimesheetRow

EMPLOYEE_ID = "MTG-TF/TEST"
LIBUR_DAY = date(2026, 9, 22)
WORK_DAY = date(2026, 9, 21)


def _employee() -> Employee:
    return Employee(EmployeeId(EMPLOYEE_ID), "TEST", "Gading Aulia", EmployeeRole.IOT_OPERATIONS)


def _row(day: date, *, remarks: str = "SHIFT 1", is_holiday: bool = False) -> _TimesheetRow:
    return _TimesheetRow(
        "pipeline",
        f"ts-{day}",
        EMPLOYEE_ID,
        day,
        "P05-Support",
        "Panel Project",
        is_holiday,
        remarks,
        1,
        datetime.now(UTC),
    )


def _punch(day: date, check_in: str, check_out: str) -> _AttendanceRow:
    return _AttendanceRow(
        "pipeline", f"at-{day}", EMPLOYEE_ID, day, check_in, check_out, 1, datetime.now(UTC)
    )


def _rows(report: dict[str, object] | None) -> dict[str, dict[str, str]]:
    assert report is not None
    return {row["Date"]: row for row in report["timesheet_rows"]}  # type: ignore[index,union-attr]


def _report(timesheets, attendance, schedule_off, absences=None):  # noqa: ANN001, ANN202
    return _timesheet_report(
        _employee(),
        WORK_DAY,
        LIBUR_DAY,
        timesheets,
        attendance,
        absences or {},
        "",
        "September",
        2026,
        frozenset(schedule_off),
    )


def test_stale_working_row_on_a_scheduled_libur_day_renders_as_libur() -> None:
    # The Gading case: schedule = Libur, row still "SHIFT 1" with project filled, no punches.
    report = _report(
        {WORK_DAY: _row(WORK_DAY), LIBUR_DAY: _row(LIBUR_DAY)},
        {WORK_DAY: _punch(WORK_DAY, "06:54", "15:03")},
        {LIBUR_DAY},
    )
    row = _rows(report)["Tue, Sep 22, 2026"]

    assert row["Remarks"] == "Libur"
    assert row["Is Holiday"] == "H"
    assert row["Activity"] == ""
    assert row["Project Name"] == ""
    assert row["Total Hours"] == ""


def test_the_normal_working_day_next_to_it_is_untouched() -> None:
    report = _report(
        {WORK_DAY: _row(WORK_DAY), LIBUR_DAY: _row(LIBUR_DAY)},
        {WORK_DAY: _punch(WORK_DAY, "06:54", "15:03")},
        {LIBUR_DAY},
    )
    row = _rows(report)["Mon, Sep 21, 2026"]

    assert row["Remarks"] == "SHIFT 1"
    assert row["Is Holiday"] == ""
    assert row["Start Time"] == "06:54"
    assert row["Total Hours"] == "7.15"


def test_without_schedule_information_nothing_changes() -> None:
    # Developer reports and the previous behaviour pass no schedule-off days.
    report = _report({LIBUR_DAY: _row(LIBUR_DAY)}, {}, set())
    row = _rows(report)["Tue, Sep 22, 2026"]

    assert row["Remarks"] == "SHIFT 1"
    assert row["Is Holiday"] == ""
    assert row["Total Hours"] == "0.00"


def test_real_clock_in_and_out_on_a_scheduled_libur_day_keeps_the_hours() -> None:
    # They worked on their day off: the hours are real, never wiped by the schedule.
    report = _report(
        {LIBUR_DAY: _row(LIBUR_DAY)}, {LIBUR_DAY: _punch(LIBUR_DAY, "07:00", "15:00")}, {LIBUR_DAY}
    )
    row = _rows(report)["Tue, Sep 22, 2026"]

    assert row["Remarks"] == "SHIFT 1"
    assert row["Is Holiday"] == ""
    assert row["Start Time"] == "07:00"
    assert row["Total Hours"] == "7.00"


def test_a_row_already_marked_libur_is_unchanged() -> None:
    report = _report(
        {LIBUR_DAY: _row(LIBUR_DAY, remarks="Libur", is_holiday=True)}, {}, {LIBUR_DAY}
    )
    row = _rows(report)["Tue, Sep 22, 2026"]

    assert (row["Remarks"], row["Is Holiday"]) == ("Libur", "H")


def test_an_approved_absence_still_wins_over_the_schedule() -> None:
    report = _report({LIBUR_DAY: _row(LIBUR_DAY)}, {}, {LIBUR_DAY}, {LIBUR_DAY: "sakit"})
    row = _rows(report)["Tue, Sep 22, 2026"]

    assert (row["Remarks"], row["Is Holiday"]) == ("Sakit", "H")


def test_a_scheduled_libur_day_with_no_timesheet_row_is_marked_libur() -> None:
    report = _report(
        {WORK_DAY: _row(WORK_DAY)}, {WORK_DAY: _punch(WORK_DAY, "06:54", "15:03")}, {LIBUR_DAY}
    )
    row = _rows(report)["Tue, Sep 22, 2026"]

    assert (row["Remarks"], row["Is Holiday"]) == ("Libur", "H")
