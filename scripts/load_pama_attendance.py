"""Load raw PAMA attendance + IoT shift roster directly into durable_records.

Bypasses NocoDB (unreachable): reads check-in/out straight from the legacy
SQL Server (db_attendance/db_pamamobile), reads IoT Operation shift codes from
a locally exported roster CSV, and reuses domain.timesheets.day_status() so
the Shift/Keterangan columns match what the NocoDB-backed pipeline used to
produce. Writes flat attendance rows the existing PostgresWebBackend query
already expects (see web/postgres_sql.py ATTENDANCE).

Usage:
    APP_DATABASE_DSN=postgresql://... python scripts/load_pama_attendance.py \\
        --employees employee_data.json --roster "simulasi shifting(Schedule Shifting).csv" \\
        --start 2026-07-01 --end 2026-09-01 \\
        --sql-server jiepsqco423 --sql-user mobile_user --sql-password ...
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import holidays
import psycopg
import pymssql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from digital_bast.domain.identity import daily_key, holiday_key
from digital_bast.domain.models import (
    EmployeeRole,
    Holiday,
    RecordOrigin,
    Schedule,
)
from digital_bast.domain.timesheets import day_status
from digital_bast.infrastructure.pama_attendance import (
    ATTENDANCE_QUERY,
    DEVELOPER_SCHEDULE,
    SHIFT_LEGEND,
    parse_clock,
)


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    full_name: str
    employee_id: str
    nrp: str
    role: EmployeeRole


def load_employees(path: Path) -> tuple[EmployeeRecord, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        EmployeeRecord(
            full_name=item["full_name"],
            employee_id=item["employee_id"],
            nrp=item["nrp"],
            role=(
                EmployeeRole.DEVELOPER
                if item["role"] == "Developer"
                else EmployeeRole.IOT_OPERATIONS
            ),
        )
        for item in raw
    )


def daterange(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


_ROSTER_START_YEAR = 2024
_ROSTER_START_MONTH = 3  # sheet's first month block is March 2024


def load_roster(path: Path, employees: tuple[EmployeeRecord, ...]) -> dict[tuple[str, date], str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    month_header = rows[10]
    month_columns = [index for index, value in enumerate(month_header) if value.strip()]
    day_row = rows[12]
    names = {
        employee.full_name for employee in employees if employee.role is EmployeeRole.IOT_OPERATIONS
    }
    roster: dict[tuple[str, date], str] = {}
    for row in rows[13:]:
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        matched = next((name for name in names if name.lower() in label.lower()), None)
        if matched is None:
            continue
        if not any(value.strip() for value in row[1:]):
            continue
        boundaries = list(zip(month_columns, [*month_columns[1:], len(row)], strict=True))
        for block_index, (col_index, col_end) in enumerate(boundaries):
            total_month = (_ROSTER_START_MONTH - 1) + block_index
            year_num = _ROSTER_START_YEAR + total_month // 12
            month_num = total_month % 12 + 1
            for offset in range(col_index, min(col_end, len(row))):
                day_text = day_row[offset].strip()
                if not day_text.isdigit():
                    continue
                code = row[offset].strip()
                if not code:
                    continue
                try:
                    work_date = date(year_num, month_num, int(day_text))
                except ValueError:
                    continue
                roster[(matched, work_date)] = code
    return roster


def fetch_attendance(
    connection: pymssql.Connection, nrp: str, start: date, end: date
) -> dict[date, tuple[str, str]]:
    cursor = connection.cursor()
    cursor.execute(ATTENDANCE_QUERY, (nrp, start, end))
    by_date: dict[date, list[str]] = {}
    for attendance_date, label in cursor.fetchall():
        by_date.setdefault(attendance_date, []).append(label)
    cursor.close()
    result: dict[date, tuple[str, str]] = {}
    for work_date, labels in by_date.items():
        check_in = ""
        check_out = ""
        for label in sorted(labels):
            if "(IN)" in label and not check_in:
                check_in = label.replace(" (IN)", "").strip()
            elif "(OUT)" in label:
                check_out = label.replace(" (OUT)", "").strip()
        result[work_date] = (check_in, check_out)
    return result


def build_rows(
    employee: EmployeeRecord,
    dates: list[date],
    attendance: dict[date, tuple[str, str]],
    roster: dict[tuple[str, date], str],
    id_holidays: holidays.HolidayBase,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for work_date in dates:
        check_in, check_out = attendance.get(work_date, ("", ""))
        if employee.role is EmployeeRole.IOT_OPERATIONS:
            code = roster.get((employee.full_name, work_date))
            if code is None:
                shift_name = None
            else:
                label, _sched_in, _sched_out = SHIFT_LEGEND.get(code, (code, "", ""))
                shift_name = label
            schedule = Schedule(
                daily_key("schedule", work_date, employee.employee_id),
                employee.employee_id,  # type: ignore[arg-type]
                work_date,
                shift_name,
                RecordOrigin.PIPELINE,
            )
            is_holiday, notes = day_status(employee.role, work_date.weekday(), None, schedule)
            has_schedule = code is not None and code in SHIFT_LEGEND
            if has_schedule and code not in ("L", "LS", "TS", "C", "I"):
                _, schedule_in, schedule_out = SHIFT_LEGEND[code]
            else:
                schedule_in, schedule_out = "", ""
            shift = "Day Off" if is_holiday else (shift_name or "")
        else:
            holiday_name = id_holidays.get(work_date)
            holiday = (
                Holiday(holiday_key(work_date), work_date, str(holiday_name))
                if holiday_name is not None
                else None
            )
            is_holiday, notes = day_status(employee.role, work_date.weekday(), holiday, None)
            has_punch = bool(check_in or check_out)
            if is_holiday or not has_punch:
                shift, schedule_in, schedule_out = "Day Off", "", ""
            else:
                shift, schedule_in, schedule_out = "N", *DEVELOPER_SCHEDULE
        rows.append(
            {
                "employee_id": employee.employee_id,
                "full_name": employee.full_name,
                "role": str(employee.role),
                "shift": shift,
                "schedule_in": schedule_in,
                "schedule_out": schedule_out,
                "attendance_code": "",
                "check_in": check_in,
                "check_out": check_out,
                "notes": notes,
                "work_date": work_date.isoformat(),
            }
        )
    return rows


def upsert(connection: psycopg.Connection, row: dict[str, object]) -> None:
    """Same target and guard as the ingest endpoint (web/sync_router.py).

    This script is the fallback for a direct run from inside the PAMA network;
    the normal path is bridge/pama_bridge.py posting to /internal/sync.
    """
    work_date = date.fromisoformat(str(row["work_date"]))
    connection.execute(
        """
        INSERT INTO attendance (
            record_key, employee_id, work_date, shift, schedule_in,
            schedule_out, attendance_code, check_in, check_out, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (record_key) DO UPDATE SET
            shift = EXCLUDED.shift,
            schedule_in = EXCLUDED.schedule_in,
            schedule_out = EXCLUDED.schedule_out,
            attendance_code = EXCLUDED.attendance_code,
            check_in = EXCLUDED.check_in,
            check_out = EXCLUDED.check_out,
            notes = EXCLUDED.notes
        WHERE attendance.origin <> 'manual'
        """,
        (
            str(daily_key("attendance", work_date, str(row["employee_id"]))),
            row["employee_id"],
            work_date,
            row["shift"],
            row["schedule_in"],
            row["schedule_out"],
            row["attendance_code"],
            parse_clock(str(row["check_in"])),
            parse_clock(str(row["check_out"])),
            row["notes"],
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--employees", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--sql-server", required=True)
    parser.add_argument("--sql-user", required=True)
    parser.add_argument("--sql-password", required=True)
    parser.add_argument("--sql-database", default="db_pamamobile")
    parser.add_argument("--postgres-dsn", required=True)
    args = parser.parse_args()

    employees = load_employees(args.employees)
    roster = load_roster(args.roster, employees)
    dates = daterange(args.start, args.end)
    years = sorted({args.start.year, args.end.year})
    id_holidays = holidays.ID(years=years)

    sql_conn = pymssql.connect(
        server=args.sql_server,
        user=args.sql_user,
        password=args.sql_password,
        database=args.sql_database,
        timeout=30,
        login_timeout=15,
    )
    pg_conn = psycopg.connect(args.postgres_dsn, autocommit=True)

    total = 0
    for employee in employees:
        attendance = fetch_attendance(sql_conn, employee.nrp, args.start, args.end)
        rows = build_rows(employee, dates, attendance, roster, id_holidays)
        for row in rows:
            upsert(pg_conn, row)
            total += 1
        print(f"{employee.full_name}: {len(rows)} rows")

    sql_conn.close()
    pg_conn.close()
    print(f"done. {total} rows upserted into durable_records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
