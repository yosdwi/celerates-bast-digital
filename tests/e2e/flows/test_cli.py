from __future__ import annotations

import json
from typing import TYPE_CHECKING

from digital_bast.cli import main

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


def test_list_reports_deployable_schedule_contract(capsys: CaptureFixture[str]) -> None:
    exit_code = main(["list"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(payload) == 5
    assert all(item["timezone"] == "Asia/Jakarta" for item in payload)
    assert all(item["concurrency_limit"] == 1 for item in payload)


def test_timesheet_backfill_dry_run_requires_and_preserves_explicit_period(
    capsys: CaptureFixture[str],
) -> None:
    exit_code = main(["backfill-timesheets", "--period", "2024-02", "--dry-run"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {"dry_run": True, "flow": "monthly-timesheets", "period": "2024-02"}


def test_timesheet_backfill_rejects_invalid_period(capsys: CaptureFixture[str]) -> None:
    exit_code = main(["backfill-timesheets", "--period", "2024-13", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "expected YYYY-MM" in captured.err
