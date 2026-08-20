"""Poll the Sheets relay and replay whatever the PAMA bridge left there.

The PAMA office network cannot reach this VPS at all -- SSH resets network-wide
and TLS to every *.celeratesapps.com host is SNI-blocked -- and it also blocks
Google's Drive/Dropbox storage APIs specifically, but not Google Sheets
(verified 2026-08-20). `bridge/pama_bridge.py --dump --upload-sheet` appends
one row per payload file to a shared relay sheet from that side; this runs
from inside the VPS (which reaches both Sheets and the app's own ingest
endpoint) and replays each row, then deletes it once its replay succeeds -- a
failed row is simply left for the next poll to retry, no separate retry/dedup
bookkeeping needed, since ingest is upsert-idempotent on `record_key` (a
deterministic hash of the source row): re-sending a row twice, or a whole
overlapping lookback window every run, is a no-op the second time and an
update whenever the underlying row actually changed (e.g. a task closing
later). Duplicate-safety and "history stays current" both come from that
ingest design, not from anything this poller does.

Run this often (every 10-30 minutes) and keep the PAMA-side dump's lookback
window short (`SYNC_LOOKBACK_DAYS`, a day or two) to match -- a frequent,
narrow dump stays fast; the lookback only needs to be wide enough to
self-heal a single missed run, not to re-cover the whole history every time.

    python scripts/sheet_replay_poller.py

Meant to run on a schedule (cron on the host, `docker exec` into a running
container -- see docs/vps-migration-status.md). Exits non-zero on any failure
so a cron entry shows it as failed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

_INGEST_BASE_URL = "http://reverse-proxy:8080"
_TIMEOUT_SECONDS = 60.0
_SHEET_RANGE = "A:B"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        message = f"{name} is required"
        raise SystemExit(message)
    return value


def _sheets_service() -> Any:  # noqa: ANN401
    from google.oauth2 import service_account  # noqa: PLC0415
    from googleapiclient.discovery import build  # noqa: PLC0415

    key_path = Path(_env("GOOGLE_SHEETS_RELAY_CREDENTIALS"))
    if not key_path.exists():
        message = f"Sheets relay credentials not found: {key_path}"
        raise SystemExit(message)
    credentials = service_account.Credentials.from_service_account_file(
        str(key_path), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _pending_rows(service: Any, sheet_id: str) -> list[tuple[int, str, str]]:  # noqa: ANN401
    result = (
        service.spreadsheets().values().get(spreadsheetId=sheet_id, range=_SHEET_RANGE).execute()
    )
    rows: list[tuple[int, str, str]] = []
    for index, row in enumerate(result.get("values", [])):
        if len(row) < 2 or not row[0].strip():  # noqa: PLR2004
            continue
        rows.append((index, row[0], row[1]))
    return rows


def _delete_rows(service: Any, sheet_id: str, row_indices: list[int]) -> None:  # noqa: ANN401
    if not row_indices:
        return
    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": 0,
                    "dimension": "ROWS",
                    "startIndex": index,
                    "endIndex": index + 1,
                }
            }
        }
        # Highest index first: deleting a lower row would shift every row
        # below it up by one, invalidating the indices still queued here.
        for index in sorted(row_indices, reverse=True)
    ]
    body = {"requests": requests}
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()


def main() -> int:
    sheet_id = _env("GOOGLE_SHEETS_RELAY_SHEET_ID")
    token_path = Path(os.environ.get("SYNC_INGEST_TOKEN_FILE", "/run/secrets/sync_ingest_token"))
    token = token_path.read_text(encoding="utf-8").strip()

    service = _sheets_service()
    pending = _pending_rows(service, sheet_id)
    if not pending:
        print("nothing pending")
        return 0

    failures: list[str] = []
    done_rows: list[int] = []
    replayed = 0
    with httpx.Client(base_url=_INGEST_BASE_URL, timeout=_TIMEOUT_SECONDS) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        for row_index, name, payload_json in pending:
            try:
                item = json.loads(payload_json)
                response = client.post(item["path"], json=item["payload"])
                _ = response.raise_for_status()
                result = response.json()
            except Exception as error:  # noqa: BLE001
                failures.append(name)
                print(f"{name} failed: {error}", file=sys.stderr)
                continue
            replayed += int(result.get("upserted", 0))
            done_rows.append(row_index)
            print(f"{name} -> {result}")

    _delete_rows(service, sheet_id, done_rows)

    print(f"replayed {replayed} rows from {len(done_rows)} files")
    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
