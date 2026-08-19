"""Seed the `employees` table from the existing NocoDB "Employee Data" table.

One-off bootstrap for the migration. NocoDB's roster is the authoritative one:
it holds the correct NRPs (JIMT25004 / JIMT22012 / JIMT24002 -- verified
2026-08-19), whereas employee_data.json carried a leading "L" typo on exactly
those three for months, silently dropping 100% of their tasks and attendance.
It also spells the role "IoT Operations", matching EmployeeRole, while the JSON
said "IoT Operation".

Reads NocoDB, writes app Postgres. Never writes NocoDB.

    python scripts/seed_employees_from_nocodb.py \
        --nocodb-dsn postgresql://... --base-id pc38r6u1npuq0ul \
        --postgres-dsn postgresql://...

With no DSN arguments it falls back to NOCODB_DATABASE_DSN / NOCODB_BASE_ID /
APP_DATABASE_DSN from the environment.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg import sql

_VALID_ROLES = frozenset({"Developer", "IoT Operations"})


def fetch_roster(nocodb_dsn: str, base_id: str) -> list[tuple[str, str, str, str, str, str]]:
    query = sql.SQL(
        """
        SELECT "Employee_ID", "NRP", "Employee_Name", "Role",
               COALESCE("Status", 'Active'), COALESCE("Grade", '')
        FROM {schema}."Employee Data"
        WHERE "Employee_ID" IS NOT NULL AND "NRP" IS NOT NULL
        ORDER BY "Role", "Employee_Name"
        """
    ).format(schema=sql.Identifier(base_id))
    with psycopg.connect(nocodb_dsn, connect_timeout=10) as connection:
        return [
            (str(a), str(b), str(c), str(d), str(e), str(f))
            for a, b, c, d, e, f in connection.execute(query).fetchall()
        ]


def seed(postgres_dsn: str, rows: list[tuple[str, str, str, str, str, str]]) -> tuple[int, int]:
    written = 0
    skipped = 0
    with psycopg.connect(postgres_dsn, connect_timeout=10) as connection:
        for employee_id, nrp, full_name, role, status, grade in rows:
            if role.strip() not in _VALID_ROLES:
                print(f"  skip {full_name}: unknown role {role!r}", file=sys.stderr)
                skipped += 1
                continue
            # Never clobber a row someone edited in NocoDB-v2 -- same guard the
            # pipeline upserts use.
            _ = connection.execute(
                """
                INSERT INTO employees (
                    employee_id, nrp, full_name, role, status, grade
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (employee_id) DO UPDATE SET
                    nrp = EXCLUDED.nrp,
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    grade = EXCLUDED.grade
                WHERE employees.origin <> 'manual'
                """,
                (employee_id.strip(), nrp.strip(), full_name.strip(), role.strip(), status, grade),
            )
            written += 1
    return written, skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nocodb-dsn", default=os.getenv("NOCODB_DATABASE_DSN"))
    parser.add_argument("--base-id", default=os.getenv("NOCODB_BASE_ID"))
    parser.add_argument("--postgres-dsn", default=os.getenv("APP_DATABASE_DSN"))
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("--nocodb-dsn", args.nocodb_dsn),
            ("--base-id", args.base_id),
            ("--postgres-dsn", args.postgres_dsn),
        )
        if not value
    ]
    if missing:
        print(f"missing: {', '.join(missing)}", file=sys.stderr)
        return 2

    rows = fetch_roster(args.nocodb_dsn, args.base_id)
    print(f"read {len(rows)} employees from NocoDB base {args.base_id}")
    written, skipped = seed(args.postgres_dsn, rows)
    print(f"seeded {written} employees ({skipped} skipped)")
    # A roster this small is verified by eye; print it so the operator can see
    # the NRPs actually landed without a leading "L".
    for employee_id, nrp, full_name, role, _status, _grade in rows:
        print(f"  {nrp:12} {employee_id:20} {role:15} {full_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
