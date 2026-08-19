import csv
import io
from collections.abc import Mapping
from datetime import date

from digital_bast.web.contracts import AttendanceRow

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
    "Employee ID", "Full Name", "Date", "Shift", "Shift Code", "Shift Label",
    "Schedule In", "Schedule Out", "Attendance Code", "Check In", "Check Out",
    "Keterangan", "Overtime Check In", "Overtime Check Out", "Overtime Before",
    "Overtime After", "TimeOff Check Out", "TimeOff Break Before",
    "TimeOff Break After", "Holiday Code",
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
        work_date = date.fromisoformat(str(row["work_date"]))
        writer.writerow(
            neutralize_csv_formula(str(value))
            for value in (
                row["employee_id"], row["full_name"], work_date.strftime("%d/%m/%Y"),
                row["shift"], "", "", row["schedule_in"], row["schedule_out"],
                row["attendance_code"], row["check_in"], row["check_out"], row["notes"],
                "", "", "", "", "", "", "", "",
            )
        )
    return output.getvalue()
