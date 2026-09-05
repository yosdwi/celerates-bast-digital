from datetime import UTC, date, datetime

from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.web.bast_assembler import (
    _AttendanceRow,
    _timesheet_report,
    _TimesheetRow,
)


def _employee() -> Employee:
    return Employee(
        EmployeeId("MTG-TF/TEST"), "TEST", "Hanung Rizqi Widianto", EmployeeRole.DEVELOPER
    )


def _timesheet_row(work_date: date, *, remarks: str, is_holiday: bool = False) -> _TimesheetRow:
    return _TimesheetRow(
        "pipeline",
        "ext-1",
        "MTG-TF/TEST",
        work_date,
        "P01-Development",
        "Some Project",
        is_holiday,
        remarks,
        1,
        datetime.now(UTC),
    )


def test_approved_absence_overrides_a_stale_pama_working_day_row() -> None:
    # PAMA already synced a normal "Working Day" timesheet row for 2026-08-03
    # (activity/project filled in, is_holiday False) even though PMO approved
    # a Sakit day for that date -- the approval must win, not the stale sync.
    start, end = date(2026, 8, 1), date(2026, 8, 3)
    timesheets = {date(2026, 8, 3): _timesheet_row(date(2026, 8, 3), remarks="Working Day")}
    attendance: dict[date, _AttendanceRow] = {}
    absences = {date(2026, 8, 3): "sakit"}

    report = _timesheet_report(
        _employee(), start, end, timesheets, attendance, absences, "", "August", 2026
    )

    assert report is not None
    rows = {row["Date"]: row for row in report["timesheet_rows"]}
    sakit_row = rows["Mon, Aug 3, 2026"]
    assert sakit_row["Remarks"] == "Sakit"
    assert sakit_row["Is Holiday"] == "H"
    assert sakit_row["Activity"] == ""
    assert sakit_row["Project Name"] == ""
    assert sakit_row["Total Hours"] == ""


def test_working_day_without_an_approved_absence_is_unaffected() -> None:
    start = end = date(2026, 8, 3)
    timesheets = {date(2026, 8, 3): _timesheet_row(date(2026, 8, 3), remarks="Working Day")}
    attendance = {
        date(2026, 8, 3): _AttendanceRow(
            "pipeline",
            "ext-1",
            "MTG-TF/TEST",
            date(2026, 8, 3),
            "07:20",
            "17:00",
            1,
            datetime.now(UTC),
        )
    }
    absences: dict[date, str] = {}

    report = _timesheet_report(
        _employee(), start, end, timesheets, attendance, absences, "", "August", 2026
    )

    assert report is not None
    row = report["timesheet_rows"][0]
    assert row["Remarks"] == "Working Day"
    assert row["Is Holiday"] == ""
    assert row["Start Time"] == "07:20"
