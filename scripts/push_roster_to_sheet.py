"""Refresh the roster snapshot the PAMA bridge reads when it can't reach the VPS.

`pama_bridge.py --dump` needs a roster (NRP -> name/role) to run its SQL
queries, but it can't ask the VPS for one live -- the PAMA network can't reach
it at all, which is the whole reason --dump/--upload-sheet exist. A static
local `employee_data.json` copy was the fallback, and it going stale
(uncorrected NRPs, missed roster changes) is exactly the failure class that
cost a leading-"L" typo months of silently dropped attendance/tasks for three
people. This overwrites a "Roster" tab in the same relay spreadsheet with the
current `employees` table on every run, so `--dump` can read a fresh roster
from Sheets (reachable from PAMA) instead of a snapshot someone has to
remember to update by hand.

    python scripts/push_roster_to_sheet.py

Meant to run on a schedule (roster changes rarely -- hourly is plenty). Exits
non-zero on failure so a cron entry shows it as failed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio

from digital_bast.operations import load_roster

if TYPE_CHECKING:
    from digital_bast.domain.models import Employee

_ROSTER_TAB = "Roster"
_HEADER = ["full_name", "employee_id", "nrp", "role"]


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


def _ensure_roster_tab(service: Any, sheet_id: str) -> None:  # noqa: ANN401
    fields = "sheets.properties.title"
    meta = service.spreadsheets().get(spreadsheetId=sheet_id, fields=fields).execute()
    titles = {sheet["properties"]["title"] for sheet in meta.get("sheets", [])}
    if _ROSTER_TAB in titles:
        return
    body = {"requests": [{"addSheet": {"properties": {"title": _ROSTER_TAB}}}]}
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()


def _push(service: Any, sheet_id: str, roster: tuple[Employee, ...]) -> None:  # noqa: ANN401
    _ensure_roster_tab(service, sheet_id)
    rows = [_HEADER]
    rows.extend(
        [employee.name, str(employee.id), employee.external_id, str(employee.role)]
        for employee in roster
    )
    values = service.spreadsheets().values()
    _ = values.clear(spreadsheetId=sheet_id, range=_ROSTER_TAB).execute()
    _ = values.update(
        spreadsheetId=sheet_id,
        range=f"{_ROSTER_TAB}!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()


def main() -> int:
    roster = anyio.run(load_roster)
    service = _sheets_service()
    sheet_id = _env("GOOGLE_SHEETS_RELAY_SHEET_ID")
    _push(service, sheet_id, roster)
    print(f"pushed {len(roster)} employees to the {_ROSTER_TAB} tab")
    return 0


if __name__ == "__main__":
    sys.exit(main())
