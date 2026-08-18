from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

from digital_bast import cli
from digital_bast.cli import main
from digital_bast.domain.completion import (
    AttendanceFact,
    CompletionReport,
    DateRange,
    EmployeeFacts,
    TaskFact,
    TimesheetFact,
    evaluate_completion,
)
from digital_bast.infrastructure.docker_status import (
    DockerUnavailableError,
    ServiceStatus,
    SystemStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from _pytest.capture import CaptureFixture

DOCKER_MISSING = "docker executable not found on PATH"


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


def _completion_report() -> CompletionReport:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 2))
    facts = EmployeeFacts(
        employee_id="7",
        name="Titin",
        off_days=frozenset({date(2026, 8, 2)}),
        attendance=(
            AttendanceFact(
                date(2026, 8, 1), has_clock_in=True, has_clock_out=True, has_evidence=False
            ),
        ),
        timesheets=(
            TimesheetFact(date(2026, 8, 1), "Shift Pagi"),
            TimesheetFact(date(2026, 8, 2), "OFF"),
        ),
        tasks=(TaskFact(date(2026, 8, 1), "CCTV Gate 2", "Closed"),),
        task_evidence_count=1,
        attendance_available=True,
    )
    return evaluate_completion(period, (facts,))


def test_completion_status_emits_machine_readable_payload(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(period: DateRange, employee: str | None = None) -> CompletionReport:
        assert period == DateRange(date(2026, 8, 1), date(2026, 8, 2))
        assert employee == "Titin"
        return _completion_report()

    monkeypatch.setattr(cli, "completion_status", fake)

    exit_code = cli.main(
        [
            "completion-status",
            "--start-date",
            "2026-08-01",
            "--end-date",
            "2026-08-02",
            "--employee",
            "Titin",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["start_date"] == "2026-08-01"
    assert payload["state"] == "complete"
    assert payload["employees"][0]["timesheet"] == {"state": "complete", "issues": []}


def test_completion_status_text_format_is_whatsapp_ready(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(period: DateRange, employee: str | None = None) -> CompletionReport:
        _ = (period, employee)
        return _completion_report()

    monkeypatch.setattr(cli, "completion_status", fake)

    exit_code = cli.main(
        [
            "completion-status",
            "--start-date",
            "2026-08-01",
            "--end-date",
            "2026-08-02",
            "--format",
            "text",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.startswith("*Status BAST — 1-2 Agustus 2026*")


def test_completion_status_rejects_inverted_range(capsys: CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["completion-status", "--start-date", "2026-08-31", "--end-date", "2026-08-01"]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "is before start date" in captured.err


def test_system_status_reports_overall_state(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "system_status",
        lambda: SystemStatus("healthy", (ServiceStatus("postgres", "running", "healthy"),)),
    )

    exit_code = cli.main(["system-status"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "overall": "healthy",
        "services": [{"service": "postgres", "state": "running", "health": "healthy"}],
    }


def test_system_status_reports_docker_outage(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> SystemStatus:
        raise DockerUnavailableError(DOCKER_MISSING)

    monkeypatch.setattr(cli, "system_status", unavailable)

    exit_code = cli.main(["system-status"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "docker compose status unavailable" in captured.err


def test_export_attendance_writes_csv_file(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake(period: DateRange, employees: tuple[str, ...] = ()) -> tuple[str, int]:
        assert period == DateRange(date(2026, 7, 20), date(2026, 8, 18))
        assert employees == ("Titin",)
        return "Employee ID\r\n7\r\n", 1

    monkeypatch.setattr(cli, "export_attendance", fake)
    target = tmp_path / "attendance.csv"

    exit_code = cli.main(
        [
            "export-attendance",
            "--start-date",
            "2026-07-20",
            "--end-date",
            "2026-08-18",
            "--employee",
            "Titin",
            "--label",
            "Attendance August 2026",
            "--output",
            str(target),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["rows"] == 1
    assert payload["label"] == "Attendance August 2026"
    assert target.read_bytes() == b"Employee ID\r\n7\r\n"


def test_generate_bast_writes_document(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake(period: DateRange, label: str = "") -> tuple[str, CompletionReport]:
        _ = (period, label)
        return "<html></html>", _completion_report()

    monkeypatch.setattr(cli, "generate_bast", fake)
    target = tmp_path / "bast.html"

    exit_code = cli.main(
        [
            "generate-bast",
            "--start-date",
            "2026-08-01",
            "--end-date",
            "2026-08-02",
            "--output",
            str(target),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["employees"] == 1
    assert target.read_text(encoding="utf-8") == "<html></html>"


def test_bot_reply_refuses_container_mutation(capsys: CaptureFixture[str]) -> None:
    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot restart worker"])

    assert exit_code == 0
    assert "hanya mendukung pemeriksaan status" in capsys.readouterr().out


def test_bot_reply_requires_a_date_range(capsys: CaptureFixture[str]) -> None:
    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot status BAST"])

    assert exit_code == 0
    assert "Mohon sertakan rentang tanggal" in capsys.readouterr().out


def test_bot_reply_formats_completion(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(period: DateRange, employee: str | None = None) -> CompletionReport:
        _ = (period, employee)
        return _completion_report()

    monkeypatch.setattr(cli, "completion_status", fake)

    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot status 1 sampai 2 Agustus 2026"])

    assert exit_code == 0
    assert "Timesheet ✅" in capsys.readouterr().out
