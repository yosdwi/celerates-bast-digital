"""Import Schedule Shifting from the roster CSV into the `schedules` table.

Replaces reading shift schedules out of NocoDB. The expected layout is the one
in `simulasi shifting(Schedule Shifting).csv`: a legend block, then a month
header row, a weekday row, a day-number row, and one row per IoT Operations
employee whose first cell contains their name.

The row-parsing itself lives in
digital_bast.infrastructure.production_sources.parse_schedule_rows, not here
-- this script is just the CSV-reading + Postgres-writing wrapper around it,
so there is exactly one place that understands this layout.

    python scripts/import_schedule_csv.py \
        --csv "simulasi shifting(Schedule Shifting).csv" \
        --postgres-dsn postgresql://...
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from digital_bast.domain.identity import daily_key
from digital_bast.infrastructure.pama_attendance import SHIFT_LEGEND
from digital_bast.infrastructure.production_sources import parse_schedule_rows

if TYPE_CHECKING:
    from datetime import date


def load_employees(dsn: str) -> dict[str, str]:
    """IoT Operations roster as {full_name: employee_id}.

    Read from Postgres rather than a file so the schedule import joins against
    the same roster everything else uses.
    """
    with psycopg.connect(dsn, connect_timeout=10) as connection:
        return {
            str(name): str(employee_id)
            for name, employee_id in connection.execute(
                "SELECT full_name, employee_id FROM employees"
                " WHERE role = 'IoT Operations' AND status = 'Active'"
            ).fetchall()
        }


def parse_csv(path: Path, names: dict[str, str]) -> dict[tuple[str, date], str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    return parse_schedule_rows(rows, names)


def write(dsn: str, schedule: dict[tuple[str, date], str]) -> int:
    written = 0
    with psycopg.connect(dsn, connect_timeout=10) as connection:
        for (employee_id, work_date), code in sorted(schedule.items()):
            shift_name = SHIFT_LEGEND.get(code, (code, "", ""))[0]
            _ = connection.execute(
                """
                INSERT INTO schedules (record_key, employee_id, work_date, shift_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    shift_name = EXCLUDED.shift_name
                WHERE schedules.origin <> 'manual'
                """,
                (
                    str(daily_key("schedule", work_date, employee_id)),
                    employee_id,
                    work_date,
                    shift_name,
                ),
            )
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--postgres-dsn", default=os.getenv("APP_DATABASE_DSN"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.postgres_dsn:
        print("missing --postgres-dsn (or APP_DATABASE_DSN)", file=sys.stderr)
        return 2

    names = load_employees(args.postgres_dsn)
    if not names:
        print("no active IoT Operations employees found; seed the roster first", file=sys.stderr)
        return 1
    schedule = parse_csv(args.csv, names)
    if not schedule:
        print("no schedule rows parsed; check the CSV layout", file=sys.stderr)
        return 1

    days = sorted({work_date for _employee, work_date in schedule})
    print(f"parsed {len(schedule)} shift days for {len(names)} employees")
    print(f"range {days[0]} .. {days[-1]}")
    if args.dry_run:
        return 0
    print(f"wrote {write(args.postgres_dsn, schedule)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
