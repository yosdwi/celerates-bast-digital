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


def test_real_shift_data_is_never_overridden_by_schedule_fallback() -> None:
    csv_text = legacy_attendance_csv(
        (_row(shift="SHIFT 1", schedule_in="07:00", schedule_out="15:00", schedule_shift_name="SHIFT 3"),)
    )

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert fields[3] == "SHIFT 1"
    assert fields[6] == "07:00"
    assert fields[7] == "15:00"


def test_no_schedule_row_leaves_shift_blank() -> None:
    csv_text = legacy_attendance_csv((_row(),))

    fields = csv_text.strip().split("\r\n")[1].split(";")
    assert fields[3] == ""
    assert fields[6] == ""
    assert fields[7] == ""
