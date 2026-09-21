import csv
import io
from collections.abc import Mapping
from datetime import date
from typing import Final

from digital_bast.infrastructure.pama_attendance import SHIFT_LEGEND
from digital_bast.web.contracts import AttendanceRow

# Reverse of SHIFT_LEGEND (shift_code -> (shift_name, schedule_in, schedule_out)),
# keyed by name instead: schedules.shift_name already stores the resolved name,
# not the raw code, so this is what a row missing schedule_in/out (an
# evidence-upload stub the sync never populated) falls back through. Built
# from SHIFT_LEGEND rather than hand-duplicated so the two can't drift.
_SHIFT_NAME_TIMES: Final[dict[str, tuple[str, str]]] = {
    name: (schedule_in, schedule_out) for name, schedule_in, schedule_out in SHIFT_LEGEND.values()
}

CSV_HEADERS = (
    "Employee ID",
    "Full Name",
    "Date",
    "Shift",
    "Schedule In",
    "Schedule Out",
    "Attendance Code",
    "Check In",
    "Check Out",
    "Keterangan",
)

LEGACY_CSV_HEADERS = (
    "Employee ID",
    "Full Name",
    "Date",
    "Shift",
    "Shift Code",
    "Shift Label",
    "Schedule In",
    "Schedule Out",
    "Attendance Code",
    "Check In",
    "Check Out",
    "Keterangan",
    "Overtime Check In",
    "Overtime Check Out",
    "Overtime Before",
    "Overtime After",
    "TimeOff Check Out",
    "TimeOff Break Before",
    "TimeOff Break After",
    "Holiday Code",
)


def neutralize_csv_formula(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def attendance_csv(rows: tuple[AttendanceRow, ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    for row in rows:
        writer.writerow(
            neutralize_csv_formula(value)
            for value in (
                row.employee_id,
                row.full_name,
                row.work_date.isoformat(),
                row.shift,
                row.schedule_in,
                row.schedule_out,
                row.attendance_code,
                row.check_in,
                row.check_out,
                row.notes,
            )
        )
    return output.getvalue()


def legacy_attendance_csv(rows: tuple[Mapping[str, object], ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(LEGACY_CSV_HEADERS)
    for row in rows:
        # payload is legacy JSONB written by older/manual imports -- some rows
        # (e.g. seed/test fixtures) are missing keys entirely, so read
        # defensively rather than crashing the whole export on one bad row.
        raw_work_date = row.get("work_date")
        work_date_display = (
            date.fromisoformat(str(raw_work_date)).strftime("%d/%m/%Y") if raw_work_date else ""
        )
        shift = str(row.get("shift") or "")
        schedule_in = str(row.get("schedule_in") or "")
        schedule_out = str(row.get("schedule_out") or "")
        if not shift:
            # The sync never sent a row for this day (e.g. an evidence-upload
            # stub) -- fall back to the roster's own schedule assignment,
            # which exists independently of any attendance punch.
            schedule_shift_name = row.get("schedule_shift_name")
            if schedule_shift_name:
                shift = str(schedule_shift_name)
                fallback_in, fallback_out = _SHIFT_NAME_TIMES.get(shift, ("", ""))
                schedule_in = schedule_in or fallback_in
                schedule_out = schedule_out or fallback_out
        writer.writerow(
            neutralize_csv_formula(str(value))
            for value in (
                row.get("employee_id", ""),
                row.get("full_name", ""),
                work_date_display,
                shift,
                "",
                "",
                schedule_in,
                schedule_out,
                row.get("attendance_code", ""),
                row.get("check_in", ""),
                row.get("check_out", ""),
                row.get("notes", ""),
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            )
        )
    return output.getvalue()
