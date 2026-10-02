from __future__ import annotations

from digital_bast.web.csv_export import legacy_attendance_csv


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "employee_id": "MTG-TF/1",
        "full_name": "Bayu Sutra",
        "work_date": "2026-08-01",
        "shift": "",
        "schedule_in": "",
        "schedule_out": "",
        "schedule_shift_name": None,
        "attendance_code": "",
        "check_in": "",
        "check_out": "",
        "notes": "",
    }
    base.update(overrides)
    return base


def test_empty_shift_falls_back_to_roster_schedule() -> None:
    """A row the sync never populated (e.g. an evidence-upload stub) still
    has a roster shift assignment in the schedules table -- the export
    should show it instead of leaving Shift/Schedule blank.
    """
    csv_text = legacy_attendance_csv((_row(schedule_shift_name="SHIFT 3"),))

    lines = csv_text.strip().split("\r\n")
    fields = lines[1].split(";")
    # Employee ID, Full Name, Date, Shift, Shift Code, Shift Label,
    # Schedule In, Schedule Out, ...
    assert fields[3] == "SHIFT 3"
    assert fields[6] == "23:00"
    assert fields[7] == "07:00"


def test_absence_shift_name_falls_back_with_empty_schedule_window() -> None:
    csv_text = legacy_attendance_csv((_row(schedule_shift_name="Sakit"),))

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert fields[3] == "Sakit"
    assert fields[6] == ""
    assert fields[7] == ""


def test_real_schedule_window_is_never_overridden_by_shift_fallback() -> None:
    csv_text = legacy_attendance_csv(
        (
            _row(
                shift="SHIFT 1",
                schedule_in="07:00",
                schedule_out="15:00",
                schedule_shift_name="SHIFT 3",
            ),
        )
    )

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert fields[3] == "SHIFT 1"
    assert fields[6] == "07:00"
    assert fields[7] == "15:00"


def test_populated_shift_with_missing_schedule_window_still_backfills() -> None:
    """A day the sync DID send a real shift for, but not the schedule
    window (confirmed against live exports: "SHIFT 2" rows with a blank
    Schedule In/Out) -- the window should still resolve from the shift
    name itself, not only from the schedule_shift_name roster fallback.
    """
    csv_text = legacy_attendance_csv((_row(shift="SHIFT 2"),))

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert fields[3] == "SHIFT 2"
    assert fields[6] == "15:00"
    assert fields[7] == "23:00"


def test_no_schedule_row_leaves_shift_blank() -> None:
    csv_text = legacy_attendance_csv((_row(),))

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert fields[3] == ""
    assert fields[6] == ""
    assert fields[7] == ""


def test_missing_attendance_row_does_not_leak_none_into_csv() -> None:
    """A day with no attendance row at all (driven purely from schedules)
    has JSON null for attendance_code/check_in/check_out/notes, not missing
    keys -- row.get(key, "") returns None for those, and str(None) would
    literally write the text "None" into the CSV cell.
    """
    csv_text = legacy_attendance_csv(
        (
            _row(
                schedule_shift_name="SHIFT 3",
                attendance_code=None,
                check_in=None,
                check_out=None,
                notes=None,
            ),
        )
    )

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert "None" not in fields
