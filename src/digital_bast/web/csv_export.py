import csv
import io

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
