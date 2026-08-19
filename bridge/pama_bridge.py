"""PAMA-side sync bridge.

Runs on a Windows PC inside the PAMA network -- the only machine that can reach
the attendance SQL Server, the Redmine SQL Server, and (with the service
account) the IoT Google Sheet. The VPS resolves none of those hosts.

It does I/O only. Every transform runs on the VPS behind /internal/sync/*, so
the business rules stay in one place instead of drifting between two codebases.

    python pama_bridge.py                     # last SYNC_LOOKBACK_DAYS days
    python pama_bridge.py --since 2026-07-01  # initial seed
    python pama_bridge.py --only attendance   # attendance | redmine | iot

Recovery model: a fixed overlapping lookback window re-sent every run, with
idempotent upserts on the far side. PC offline, half-failed batch, duplicate
run and VPS restart all resolve by simply running again -- there is no cursor
to corrupt and nothing that can silently skip a day.

Exits non-zero on any failure so Windows Task Scheduler reports it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pymssql

_BATCH_SIZE = 500
_RETRIES = 3
_TIMEOUT = 120.0

# Kept identical to src/digital_bast/infrastructure/pama_attendance.py.
# The bridge cannot import the package (it ships standalone to a Windows PC),
# so this is a deliberate copy -- change both or neither.
_ATTENDANCE_QUERY = """
DECLARE @NRP AS VARCHAR(20) = %s;
DECLARE @RANGE_START AS DATE = %s;
DECLARE @RANGE_END AS DATE = %s;

WITH data_raw AS (
    SELECT h.attendance_date,
           CONCAT(FORMAT(h.att_hour, 'HH:mm'), ' (', h.att_type, ')') AS att_hour_label
    FROM [db_attendance].[attend].[tbl_t_att_daily_history] h
    LEFT JOIN [db_pamamobile].[dbo].[tbl_user] u ON u.nrp = h.nrp
    WHERE h.nrp = @NRP AND h.attendance_date BETWEEN @RANGE_START AND @RANGE_END
      AND u.is_pama = 0 AND u.active = 1
    UNION ALL
    SELECT d.attendance_date,
           CONCAT(FORMAT(d.att_hour, 'HH:mm'), ' (', d.att_type, ')') AS att_hour_label
    FROM [db_attendance].[attend].[tbl_t_att_daily] d
    LEFT JOIN [db_pamamobile].[dbo].[tbl_user] u ON u.nrp = d.nrp
    WHERE d.nrp = @NRP AND d.attendance_date BETWEEN @RANGE_START AND @RANGE_END
      AND u.is_pama = 0 AND u.active = 1
)
SELECT attendance_date, att_hour_label FROM data_raw ORDER BY attendance_date, att_hour_label;
"""

# Kept identical to production_sources.py::_REDMINE_QUERY.
_REDMINE_QUERY = """
SELECT login, nrp, nama, project_id, project_name, tracker_id, tracker_name,
       isu_id, isu_subject, description, start_date, due_date, created_on,
       closed_on, status_id, status_desc, author_id, author_name, done_ratio,
       estimated_hours, parent_id, updated_on
FROM DB_SATUPAMA_CIS.dbo.cis_jiep_tbl_redmine_bigdata_all_wi_digi
WHERE (start_date >= %s AND start_date <= %s) OR (created_on >= %s AND created_on <= %s)
ORDER BY start_date DESC, created_on DESC
"""

# Column letters the IoT sheet parser expects, in order:
# work_date, start, close, response, responder, issue_type, issue.
_SHEET_COLUMNS = ("D", "E", "P", "F", "H", "K", "M")


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default or "")
    if not value:
        print(f"missing environment variable: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


def _load_dotenv() -> None:
    path = Path(__file__).with_name(".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class Ingest:
    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {token}"},
        )

    def roster(self) -> list[dict[str, str]]:
        response = self._client.get("/internal/sync/roster")
        _ = response.raise_for_status()
        return response.json()["employees"]

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                response = self._client.post(path, json=payload)
                _ = response.raise_for_status()
                return response.json()
            except httpx.HTTPError as error:
                last = error
                if attempt < _RETRIES - 1:
                    time.sleep(2**attempt)
        raise RuntimeError(f"{path} failed after {_RETRIES} attempts: {last}")


def _mssql(server: str, user: str, password: str, database: str) -> pymssql.Connection:
    return pymssql.connect(
        server=server,
        user=user,
        password=password,
        database=database,
        timeout=60,
        login_timeout=15,
    )


def sync_attendance(ingest: Ingest, roster: list[dict[str, str]], start: date, end: date) -> int:
    rows: list[dict[str, str]] = []
    with _mssql(
        _env("PAMA_SQL_SERVER"),
        _env("PAMA_SQL_USER"),
        _env("PAMA_SQL_PASSWORD"),
        os.getenv("PAMA_SQL_DATABASE", "db_pamamobile"),
    ) as connection:
        for person in roster:
            cursor = connection.cursor()
            try:
                cursor.execute(_ATTENDANCE_QUERY, (person["nrp"], start, end))
                for attendance_date, label in cursor.fetchall():
                    rows.append(
                        {
                            "nrp": person["nrp"],
                            "att_date": str(attendance_date),
                            "att_hour_label": str(label),
                        }
                    )
            finally:
                cursor.close()

    upserted = 0
    for chunk in _chunks(rows):
        result = ingest.post("/internal/sync/attendance", {"rows": chunk})
        upserted += result["upserted"]
        if result.get("unmatched_nrps"):
            print(f"  WARNING unmatched NRPs: {result['unmatched_nrps']}", file=sys.stderr)
    print(f"attendance: {len(rows)} punches -> {upserted} employee-days")
    return upserted


def sync_redmine(ingest: Ingest, start: date, end: date) -> int:
    with _mssql(
        _env("REDMINE_DB_SERVER"),
        _env("REDMINE_DB_USERNAME"),
        _env("REDMINE_DB_PASSWORD"),
        os.getenv("REDMINE_DB_NAME", "DB_SATUPAMA_CIS"),
    ) as connection:
        cursor = connection.cursor(as_dict=True)
        try:
            cursor.execute(_REDMINE_QUERY, (start, end, start, end))
            rows = [_jsonable(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    upserted = 0
    for chunk in _chunks(rows):
        result = ingest.post(
            "/internal/sync/redmine",
            {"period_start": str(start), "period_end": str(end), "rows": chunk},
        )
        upserted += result["upserted"]
        if result.get("unmatched_nrps"):
            print(f"  WARNING unmatched NRPs: {result['unmatched_nrps']}", file=sys.stderr)
    print(f"redmine: {len(rows)} rows -> {upserted} tasks")
    return upserted


def sync_iot_sheet(ingest: Ingest, start: date, end: date) -> int:
    from google.oauth2 import service_account  # noqa: PLC0415
    from googleapiclient.discovery import build  # noqa: PLC0415

    # Resolved against this file's folder, not the process CWD: Task Scheduler
    # does not always honour "Start in", and a relative path that silently
    # misses would look like an auth failure.
    key_path = Path(_env("GOOGLE_APPLICATION_CREDENTIALS"))
    if not key_path.is_absolute():
        key_path = Path(__file__).resolve().parent / key_path
    if not key_path.exists():
        print(f"service-account key not found: {key_path}", file=sys.stderr)
        raise SystemExit(2)
    credentials = service_account.Credentials.from_service_account_file(
        str(key_path),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    sheet_name = os.getenv("GOOGLE_IOT_SHEET_NAME", "Master Support Ticket MS")
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    payload = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=_env("GOOGLE_IOT_SPREADSHEET_ID"),
            ranges=[f"'{sheet_name}'!{letter}:{letter}" for letter in _SHEET_COLUMNS],
        )
        .execute()
    )
    result = ingest.post(
        "/internal/sync/iot-sheet",
        {"period_start": str(start), "period_end": str(end), "payload": payload},
    )
    print(f"iot-sheet: {result['received']} rows -> {result['upserted']} tasks")
    return int(result["upserted"])


def _chunks(rows: list[Any]) -> list[list[Any]]:
    return [rows[index : index + _BATCH_SIZE] for index in range(0, len(rows), _BATCH_SIZE)] or [[]]


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {key: (value if _is_json_scalar(value) else str(value)) for key, value in row.items()}


def _is_json_scalar(value: Any) -> bool:  # noqa: ANN401
    return value is None or isinstance(value, str | int | float | bool)


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    parser.add_argument("--until", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--only",
        choices=("attendance", "redmine", "iot"),
        action="append",
        default=None,
    )
    args = parser.parse_args()

    end = args.until or date.today()  # noqa: DTZ011
    lookback = int(os.getenv("SYNC_LOOKBACK_DAYS", "14"))
    start = args.since or (end - timedelta(days=lookback))
    selected = set(args.only or ("attendance", "redmine", "iot"))

    ingest = Ingest(_env("BAST_INGEST_URL"), _env("BAST_INGEST_TOKEN"))
    roster = ingest.roster()
    print(f"window {start} .. {end}; roster {len(roster)} employees")

    failures: list[str] = []
    if "attendance" in selected:
        _run(failures, "attendance", lambda: sync_attendance(ingest, roster, start, end))
    if "redmine" in selected:
        _run(failures, "redmine", lambda: sync_redmine(ingest, start, end))
    if "iot" in selected:
        _run(failures, "iot", lambda: sync_iot_sheet(ingest, start, end))

    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


def _run(failures: list[str], name: str, action: Any) -> None:  # noqa: ANN401
    try:
        _ = action()
    except Exception as error:  # noqa: BLE001
        print(f"{name} failed: {error}", file=sys.stderr)
        failures.append(name)


if __name__ == "__main__":
    raise SystemExit(main())
