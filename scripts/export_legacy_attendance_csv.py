"""Export durable_records attendance into the legacy dashboard CSV format.

Matches the exact column layout the old NocoDB-backed dashboard produced
(semicolon-delimited, DD/MM/YYYY dates, 20 columns), split into one file per
role so filenames match what the WhatsApp bot will offer ("developer" /
"shifting"). Reads the same durable_records rows scripts/load_pama_attendance.py
writes; run that first.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

import psycopg

HEADERS = (
    "Employee ID", "Full Name", "Date", "Shift", "Shift Code", "Shift Label",
    "Schedule In", "Schedule Out", "Attendance Code", "Check In", "Check Out",
    "Keterangan", "Overtime Check In", "Overtime Check Out", "Overtime Before",
    "Overtime After", "TimeOff Check Out", "TimeOff Break Before",
    "TimeOff Break After", "Holiday Code",
)

ROLE_FILE_SUFFIX = {
    "Developer": "DEVELOPER",
    "IoT Operations": "SHIFTING",
}


def fetch_rows(dsn: str, start: date, end: date) -> list[dict[str, object]]:
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT payload
            FROM durable_records
            WHERE entity_kind = 'attendance' AND work_date BETWEEN %s AND %s
            ORDER BY payload->>'role', payload->>'full_name', work_date
            """,
            (start, end),
        )
        return [row[0] for row in cursor.fetchall()]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\r\n")
        writer.writerow(HEADERS)
        for row in rows:
            work_date = date.fromisoformat(str(row["work_date"]))
            writer.writerow(
                (
                    row["employee_id"], row["full_name"], work_date.strftime("%d/%m/%Y"),
                    row["shift"], "", "", row["schedule_in"], row["schedule_out"],
                    row["attendance_code"], row["check_in"], row["check_out"], row["notes"],
                    "", "", "", "", "", "", "", "",
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-dsn", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path())
    args = parser.parse_args()

    rows = fetch_rows(args.postgres_dsn, args.start, args.end)
    by_role: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_role.setdefault(str(row["role"]), []).append(row)

    label = f"{args.start.isoformat()}_to_{args.end.isoformat()}"
    for role, suffix in ROLE_FILE_SUFFIX.items():
        role_rows = by_role.get(role, [])
        out_path = args.out_dir / f"Attendance_Celerates_Combined_{label} ({suffix}).csv"
        write_csv(out_path, role_rows)
        print(f"{suffix}: {len(role_rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
