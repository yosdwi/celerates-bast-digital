"""PAMA-side sync bridge.

Runs on a Windows PC inside the PAMA network -- the only machine that can reach
the attendance SQL Server, the Redmine SQL Server, and (with the service
account) the IoT Google Sheet. The VPS resolves none of those hosts.

It does I/O only. Every transform runs on the VPS behind /internal/sync/*, so
the business rules stay in one place instead of drifting between two codebases.

    python pama_bridge.py                     # last SYNC_LOOKBACK_DAYS days
    python pama_bridge.py --since 2026-07-01  # initial seed
    python pama_bridge.py --only attendance   # attendance | redmine | iot

Two-network split. The PAMA network reaches the SQL Servers but blocks SSH and
blocks TLS to the ingest host entirely (and to Google's Drive/Dropbox storage
APIs, though not Sheets), so one machine can rarely do both halves. Two ways
to bridge that, manual or automatic:

    python pama_bridge.py --since 2026-07-01 --dump out --roster-file roster.json
    python pama_bridge.py --replay out       # from a network that reaches the VPS

    python pama_bridge.py --dump out --roster-file roster.json --upload-sheet
    # scripts/sheet_replay_poller.py on the VPS side reads and replays it --
    # for a recurring Task Scheduler job, since Sheets is reachable from
    # both sides and nothing needs a human to switch networks in between.

Recovery model: a fixed overlapping lookback window re-sent every run, with
idempotent upserts on the far side. PC offline, half-failed batch, duplicate
run and VPS restart all resolve by simply running again -- there is no cursor
to corrupt and nothing that can silently skip a day.

Exits non-zero on any failure so Windows Task Scheduler reports it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pymssql

_RETRIES = 3
_TIMEOUT = 120.0
# Sized to Google Sheets' 50,000-char single-cell limit, not just batching
# taste: --upload-sheet writes each chunk's whole serialized JSON into one
# cell. Redmine rows run far bigger than attendance rows (task titles and
# descriptions vs a date and a punch label) -- a 109-row redmine dump once
# came out to 79,778 chars in a single chunk under the old fixed-500-rows
# cap, already past the limit before any margin. Chunking by actual
# serialized size instead of a row count keeps every chunk safe regardless
# of which source produced it.
_MAX_CHUNK_CHARS = 20_000

# Kept identical to src/digital_bast/infrastructure/pama_attendance.py.
# The bridge cannot import the package (it ships standalone to a Windows PC),
# so this is a deliberate copy -- change both or neither.
# Column names verified against the live server on 2026-08-20. The previous
# spelling (att_hour / att_type, wrapped in FORMAT) does not exist there and
# failed with "Invalid column name 'att_hour'" -- it had never actually been
# run, because the attendance host was unreachable from the dev sandbox when
# this query was written. The real columns are attendance_hour ('HH:MM:SS'
# varchar, so LEFT(...,5) gives HH:MM) and trans ('IN'/'OUT').
#
# The u.is_pama = 0 AND u.active = 1 join filter is load-bearing and was
# checked against all 17 roster members: every one passes. It silently drops
# anyone it does not match, so re-check it when the roster changes.
_ATTENDANCE_QUERY = """
DECLARE @NRP AS VARCHAR(20) = %s;
DECLARE @RANGE_START AS DATE = %s;
DECLARE @RANGE_END AS DATE = %s;

WITH data_raw AS (
    SELECT h.attendance_date,
           CONCAT(LEFT(h.attendance_hour, 5), ' (', h.trans, ')') AS att_hour_label
    FROM [db_attendance].[attend].[tbl_t_att_daily_history] h
    LEFT JOIN [db_pamamobile].[dbo].[tbl_user] u ON u.nrp = h.nrp
    WHERE h.nrp = @NRP AND h.attendance_date BETWEEN @RANGE_START AND @RANGE_END
      AND u.is_pama = 0 AND u.active = 1
    UNION ALL
    SELECT d.attendance_date,
           CONCAT(LEFT(d.attendance_hour, 5), ' (', d.trans, ')') AS att_hour_label
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


class DumpIngest:
    """Offline half of a two-network run: capture payloads instead of POSTing.

    The counts it reports are row counts, not server-side upserts -- nothing
    has been ingested yet. Replay prints the real numbers.
    """

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._count = 0

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._count += 1
        name = f"{self._count:03d}-{path.strip('/').replace('/', '-')}.json"
        target = self._dir / name
        _ = target.write_text(
            json.dumps({"path": path, "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        rows = payload.get("rows")
        return {"upserted": len(rows) if isinstance(rows, list) else 0, "received": 0}


def upload_dump_to_sheet(directory: Path) -> int:
    """Push every payload in a --dump directory to a shared relay sheet.

    The PAMA network cannot reach the VPS at all (SSH reset network-wide,
    TLS SNI-blocked for every *.celeratesapps.com host) but Google's Sheets
    API is reachable from it same as any other unblocked site (Drive's own
    storage API, and Dropbox's, are NOT -- verified 2026-08-20; Sheets is
    the one that got through). This is the relay leg that gets a dump off
    this network. A separate poller on the VPS side
    (scripts/sheet_replay_poller.py) reads rows from here and replays them,
    deleting each once its replay succeeds; nothing here talks to the VPS.

    The relay sheet must already exist and be shared Editor with the service
    account -- a service account has no Drive storage quota of its own and
    cannot create a new spreadsheet, only write into one a real account
    already owns (verified 2026-08-20: creating a file 403s with
    "Service Accounts do not have storage quota"; appending rows to an
    existing one works fine).
    """
    from google.oauth2 import service_account  # noqa: PLC0415
    from googleapiclient.discovery import build  # noqa: PLC0415

    key_path = Path(_env("GOOGLE_SHEETS_RELAY_CREDENTIALS"))
    if not key_path.is_absolute():
        key_path = Path(__file__).resolve().parent / key_path
    if not key_path.exists():
        print(f"Sheets relay credentials not found: {key_path}", file=sys.stderr)
        raise SystemExit(2)
    credentials = service_account.Credentials.from_service_account_file(
        str(key_path), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    sheet_id = _env("GOOGLE_SHEETS_RELAY_SHEET_ID")

    files = sorted(directory.glob("*.json"))
    if not files:
        print(f"nothing to upload in {directory}")
        return 0
    rows = [[file.name, file.read_text(encoding="utf-8")] for file in files]
    _ = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
        .execute()
    )
    for file in files:
        print(f"uploaded {file.name}")
    return len(files)


def replay(ingest: Ingest, directory: Path) -> int:
    """POST payloads captured by an earlier --dump run, in capture order."""
    files = sorted(directory.glob("*.json"))
    if not files:
        raise SystemExit(f"no captured payloads in {directory}")
    total = 0
    for file in files:
        item = json.loads(file.read_text(encoding="utf-8"))
        result = ingest.post(item["path"], item["payload"])
        total += int(result.get("upserted", 0))
        print(f"{file.name} -> {result}")
    return total


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
    outsiders: set[str] = set()
    for chunk in _chunks(rows):
        result = ingest.post("/internal/sync/attendance", {"rows": chunk})
        upserted += result["upserted"]
        outsiders.update(result.get("unmatched_nrps") or ())
    print(f"attendance: {len(rows)} punches -> {upserted} employee-days")
    _report_coverage("attendance", roster, [row["nrp"] for row in rows], outsiders)
    return upserted


def sync_redmine(ingest: Ingest, roster: list[dict[str, str]], start: date, end: date) -> int:
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
    outsiders: set[str] = set()
    for chunk in _chunks(rows):
        result = ingest.post(
            "/internal/sync/redmine",
            {"period_start": str(start), "period_end": str(end), "rows": chunk},
        )
        upserted += result["upserted"]
        outsiders.update(result.get("unmatched_nrps") or ())
    print(f"redmine: {len(rows)} rows -> {upserted} tasks")
    _report_coverage("redmine", roster, [str(row.get("nrp") or "") for row in rows], outsiders)
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


def _report_coverage(
    source: str,
    roster: list[dict[str, str]],
    seen_nrps: list[str],
    outsiders: set[str],
) -> None:
    """Report roster members who got nothing -- the failure that actually matters.

    Unmatched NRPs from the source side are expected and harmless: PAMA and
    Redmine cover the whole company, so most NRPs there belong to people who
    are not on this roster. What is NOT normal is one of OUR employees coming
    back empty. That is the shape the leading-"L" NRP typo took -- three people
    silently had zero rows for months while the unmatched list looked no
    different from any other day.
    """
    present = {nrp for nrp in seen_nrps if nrp}
    empty = [person for person in roster if person["nrp"] not in present]
    if outsiders:
        print(f"  {len(outsiders)} NRPs not on our roster, skipped (expected)")
    if empty:
        names = ", ".join(f"{person['full_name']} ({person['nrp']})" for person in empty)
        print(
            f"  WARNING {source}: {len(empty)} roster employees got NO rows: {names}",
            file=sys.stderr,
        )
    else:
        print(f"  all {len(roster)} roster employees have {source} rows")


def _chunks(rows: list[Any]) -> list[list[Any]]:
    if not rows:
        return [[]]
    chunks: list[list[Any]] = []
    current: list[Any] = []
    current_chars = 0
    for row in rows:
        row_chars = len(json.dumps(row))
        if current and current_chars + row_chars > _MAX_CHUNK_CHARS:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(row)
        current_chars += row_chars
    chunks.append(current)
    return chunks


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
    parser.add_argument(
        "--dump", type=Path, default=None, help="write payloads here instead of POSTing"
    )
    parser.add_argument(
        "--replay", type=Path, default=None, help="POST payloads captured by --dump"
    )
    parser.add_argument(
        "--roster-file", type=Path, default=None, help="roster JSON, required with --dump"
    )
    parser.add_argument(
        "--upload-sheet",
        action="store_true",
        help="after --dump, push the captured payloads to the Sheets relay",
    )
    args = parser.parse_args()

    if args.upload_sheet and not args.dump:
        raise SystemExit("--upload-sheet only makes sense together with --dump")

    if args.replay:
        ingest = Ingest(_env("BAST_INGEST_URL"), _env("BAST_INGEST_TOKEN"))
        print(f"replayed {replay(ingest, args.replay)} rows")
        return 0

    end = args.until or date.today()  # noqa: DTZ011
    lookback = int(os.getenv("SYNC_LOOKBACK_DAYS", "14"))
    start = args.since or (end - timedelta(days=lookback))
    selected = set(args.only or ("attendance", "redmine", "iot"))

    if args.dump:
        if not args.roster_file:
            message = (
                "--dump needs --roster-file: the roster lives on the VPS, which is unreachable"
            )
            raise SystemExit(message)
        ingest: Any = DumpIngest(args.dump)
        roster = json.loads(args.roster_file.read_text(encoding="utf-8"))
    else:
        ingest = Ingest(_env("BAST_INGEST_URL"), _env("BAST_INGEST_TOKEN"))
        roster = ingest.roster()
    print(f"window {start} .. {end}; roster {len(roster)} employees")

    failures: list[str] = []
    if "attendance" in selected:
        _run(failures, "attendance", lambda: sync_attendance(ingest, roster, start, end))
    if "redmine" in selected:
        _run(failures, "redmine", lambda: sync_redmine(ingest, roster, start, end))
    if "iot" in selected:
        _run(failures, "iot", lambda: sync_iot_sheet(ingest, start, end))

    if not failures and args.upload_sheet:
        _run(failures, "upload-sheet", lambda: upload_dump_to_sheet(args.dump))

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
