from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from digital_bast import cli
from digital_bast.bot.attendance_evidence import AttendanceEvidenceCandidate
from digital_bast.bot.whatsapp import BotCommand, Intent
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
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.infrastructure.docker_status import (
    DockerUnavailableError,
    ServiceStatus,
    SystemStatus,
)
from digital_bast.web.bast_assembler import AssembledReport

if TYPE_CHECKING:
    import pytest
    from _pytest.capture import CaptureFixture

    from digital_bast.bot.evidence import EvidenceCandidate

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
        tasks=(TaskFact(date(2026, 8, 1), "CCTV Gate 2", "Closed", 1),),
        evidence_available=True,
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
    async def fake(
        period: DateRange, report_type: str = "developer"
    ) -> tuple[Path, AssembledReport]:
        assert period == DateRange(date(2026, 8, 1), date(2026, 8, 2))
        assert report_type == "developer"
        pdf_path = tmp_path / "generated.pdf"
        _ = pdf_path.write_bytes(b"%PDF-1.4 fake")
        return pdf_path, AssembledReport(
            report_type="developer",
            year=2026,
            month=8,
            fingerprint="deadbeef",
            document="<html></html>",
            editor_html="<html></html>",
        )

    monkeypatch.setattr(cli, "generate_bast", fake)
    target = tmp_path / "bast.pdf"

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
    assert payload["report_type"] == "developer"
    assert payload["fingerprint"] == "deadbeef"
    assert target.read_bytes() == b"%PDF-1.4 fake"


def test_bot_reply_refuses_container_mutation(capsys: CaptureFixture[str]) -> None:
    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot restart worker"])

    assert exit_code == 0
    assert "hanya mendukung pemeriksaan status" in capsys.readouterr().out


def test_bot_reply_requires_a_date_range(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: None)

    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot status BAST"])

    assert exit_code == 0
    assert "Mohon sertakan rentang tanggal" in capsys.readouterr().out


def test_bot_reply_formats_completion(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake(period: DateRange, employee: str | None = None) -> CompletionReport:
        _ = (period, employee)
        return _completion_report()

    matrix_path = tmp_path / "status-matrix.png"

    async def fake_matrix(period: DateRange) -> Path:
        _ = period
        return matrix_path

    monkeypatch.setattr(cli, "completion_status", fake)
    monkeypatch.setattr(cli, "generate_status_matrix", fake_matrix)
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: None)

    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot status 1 sampai 2 Agustus 2026"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "file"
    assert payload["path"] == str(matrix_path)
    assert "Talent lengkap : 1/1" in payload["caption"]
    assert "Overall        : ✅ Siap" in payload["caption"]


class _FakeInterpreter:
    def __init__(self, command: BotCommand | None) -> None:
        self._command = command

    async def interpret(self, text: str, today: object) -> BotCommand | None:
        _ = (text, today)
        return self._command


def test_bot_reply_llm_disambiguates_ambiguous_date_range(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The regex parser misreads this exact message as day "20" inside year
    # "2026" (docs/bast-e2e-plan.md §3.5) -- an LLM draft bypasses that class
    # of error entirely, so the echoed period must be 1-20 August, not 20-20.
    command = BotCommand(
        Intent.EXPORT_ATTENDANCE,
        DateRange(date(2026, 8, 1), date(2026, 8, 20)),
        report_type="shifting",
    )
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: _FakeInterpreter(command))

    async def fake_export(
        period: DateRange, report_type: str, employee: str | None = None
    ) -> tuple[Path, int]:
        assert period == DateRange(date(2026, 8, 1), date(2026, 8, 20))
        assert report_type == "shifting"
        assert employee is None
        return Path("attendance.csv"), 7

    monkeypatch.setattr(cli, "export_attendance_report", fake_export)

    exit_code = cli.main(
        ["bot-reply", "--text", "@BAST Bot shifting1 agustus 2026 - 20 agustus 2026"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "1-20 Agustus 2026" in payload["caption"]
    assert "Saya baca sebagai:" in payload["caption"]


def test_bot_reply_falls_back_to_regex_when_llm_returns_none(
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: _FakeInterpreter(None))

    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot restart worker"])

    assert exit_code == 0
    assert "hanya mendukung pemeriksaan status" in capsys.readouterr().out


def test_bot_reply_redirects_evidence_upload_typed_in_group_to_dm(
    capsys: CaptureFixture[str],
) -> None:
    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot aku mau upload evidence"])

    assert exit_code == 0
    assert "chat pribadi" in capsys.readouterr().out


def test_bot_reply_still_asks_for_a_period_when_evidence_is_not_an_upload_request(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: None)

    exit_code = cli.main(["bot-reply", "--text", "@BAST Bot evidence siapa yang kurang"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Mohon sertakan rentang tanggal" in out
    assert "chat pribadi" not in out


class _FakeActivation:
    def __init__(self, employee_id: str | None) -> None:
        self._employee_id = employee_id

    async def resolve(self, wa_jid: str) -> str | None:
        _ = wa_jid
        return self._employee_id


class _FakeEvidence:
    async def list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        _ = employee_id
        return ()

    async def active_kind(self, wa_jid: str) -> str | None:
        _ = wa_jid
        return None

    async def stashed_image(self, wa_jid: str) -> tuple[bytes, str, str] | None:
        _ = wa_jid
        return None

    async def mark_active(self, wa_jid: str) -> None:
        _ = wa_jid


class _FakeAttendanceEvidence:
    async def list_candidates(
        self, employee_id: str, dates: frozenset[date]
    ) -> tuple[AttendanceEvidenceCandidate, ...]:
        _ = (employee_id, dates)
        return ()

    async def mark_active(self, wa_jid: str) -> None:
        _ = wa_jid


_ATTENDANCE_DAY = date(2026, 8, 20)


class _FakeEvidenceActiveAttendance(_FakeEvidence):
    async def active_kind(self, wa_jid: str) -> str | None:
        _ = wa_jid
        return "attendance"


class _FakeAttendanceEvidenceOneCandidate(_FakeAttendanceEvidence):
    async def list_candidates(
        self, employee_id: str, dates: frozenset[date]
    ) -> tuple[AttendanceEvidenceCandidate, ...]:
        _ = (employee_id, dates)
        return (AttendanceEvidenceCandidate("A-1", _ATTENDANCE_DAY, "Attendance 20 Agustus", 0),)

    async def set_pending_attendance(self, wa_jid: str, attendance_key: str) -> None:
        _ = (wa_jid, attendance_key)


async def _fake_attendance_completion_status(period: DateRange) -> CompletionReport:
    _ = period
    facts = EmployeeFacts(
        employee_id="MTG-TF/TEST1",
        name="Test Talent",
        off_days=frozenset(),
        attendance=(
            AttendanceFact(
                _ATTENDANCE_DAY, has_clock_in=True, has_clock_out=False, has_evidence=False
            ),
        ),
        timesheets=(),
        tasks=(),
        evidence_available=True,
        attendance_available=True,
    )
    return evaluate_completion(DateRange(_ATTENDANCE_DAY, _ATTENDANCE_DAY), (facts,))


def test_bot_reply_attendance_index_pick_still_works(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidenceActiveAttendance)
    monkeypatch.setattr(
        cli, "create_attendance_evidence_service", _FakeAttendanceEvidenceOneCandidate
    )
    monkeypatch.setattr(cli, "completion_status", _fake_attendance_completion_status)

    exit_code = cli.main(
        ["bot-reply", "--text", "1", "--jid", "628123456789@s.whatsapp.net", "--channel", "dm"]
    )

    assert exit_code == 0
    assert 'dipilih: "Attendance 20 Agustus"' in capsys.readouterr().out


def test_bot_reply_unrelated_message_does_not_hijack_pending_attendance_pick(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: with only one attendance candidate left, word-overlap
    # caption matching used to match ANY message sharing a generic word with
    # the candidate's title ("agustus") -- even a plain question, never
    # intended as a selection reply. Only an explicit index should pick.
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidenceActiveAttendance)
    monkeypatch.setattr(
        cli, "create_attendance_evidence_service", _FakeAttendanceEvidenceOneCandidate
    )
    monkeypatch.setattr(cli, "completion_status", _fake_attendance_completion_status)

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "detail yoses agustus",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "dipilih" not in out
    assert "Kirim `attendance`" in out


async def _fake_roster_with_colleague() -> tuple[Employee, ...]:
    return (
        Employee(
            id=EmployeeId("MTG-TF/TEST1"),
            external_id="NRP1",
            name="Yoses Dwi Maheswara",
            role=EmployeeRole.DEVELOPER,
        ),
        Employee(
            id=EmployeeId("MTG-TF/OVI"),
            external_id="NRP2",
            name="Ovianto",
            role=EmployeeRole.DEVELOPER,
        ),
    )


def test_bot_reply_redirects_when_dm_tasklist_names_a_colleague(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: the DM tasklist/evidence summary only ever reads the
    # *sender's* own data -- silently showing that when the message actually
    # names someone else ("tasklist ovianto") reads as if it were that
    # person's data, which is actively misleading.
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidence)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", _FakeAttendanceEvidence)
    monkeypatch.setattr(cli, "load_roster", _fake_roster_with_colleague)

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "tasklist ovianto bulan agustus",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Ovianto" in out
    assert "cuma nampilin data kamu sendiri" in out


def test_bot_reply_dm_tasklist_with_no_other_name_still_shows_own_summary(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidence)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", _FakeAttendanceEvidence)
    monkeypatch.setattr(cli, "load_roster", _fake_roster_with_colleague)

    async def fake_completion_status(period: DateRange) -> CompletionReport:
        return evaluate_completion(period, ())

    monkeypatch.setattr(cli, "completion_status", fake_completion_status)

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "tasklist aku bulan ini",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Task List kamu" in out
    assert "cuma nampilin data kamu sendiri" not in out


class _FakeDmIntentInterpreter:
    def __init__(self, intent: str | None) -> None:
        self._intent = intent

    async def classify_dm_intent(self, text: str) -> str | None:
        _ = text
        return self._intent


def test_bot_reply_dm_falls_back_to_llm_for_tasklist_question_without_keywords(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: "yang belum closed apa aja" contains none of
    # _SUMMARY_WORDS' literal trigger words -- without the LLM fallback this
    # used to dead-end at _DM_HELP_REPLY with no attempt at understanding it.
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidence)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", _FakeAttendanceEvidence)
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: _FakeDmIntentInterpreter("tasklist"))

    async def fake_completion_status(period: DateRange) -> CompletionReport:
        return evaluate_completion(period, ())

    monkeypatch.setattr(cli, "completion_status", fake_completion_status)

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "yang belum closed apa aja",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Task List kamu" in out


def test_bot_reply_dm_falls_back_to_llm_for_attendance_question_without_keywords(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidence)
    monkeypatch.setattr(
        cli, "create_attendance_evidence_service", _FakeAttendanceEvidenceOneCandidate
    )
    monkeypatch.setattr(
        cli, "create_llm_interpreter", lambda: _FakeDmIntentInterpreter("attendance")
    )
    monkeypatch.setattr(cli, "completion_status", _fake_attendance_completion_status)

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "clock in aku yang belum lengkap yang mana",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Attendance kamu" in out


def test_bot_reply_dm_unrelated_question_still_falls_to_help_reply(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidence)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", _FakeAttendanceEvidence)
    monkeypatch.setattr(cli, "create_llm_interpreter", lambda: _FakeDmIntentInterpreter(None))

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "besok libur ya",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Kirim `evidence`" in out


def test_bot_reply_redirects_group_only_command_typed_in_dm(
    capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "create_activation_service", lambda: _FakeActivation("MTG-TF/TEST1"))
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidence)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", _FakeAttendanceEvidence)

    exit_code = cli.main(
        [
            "bot-reply",
            "--text",
            "export attendance developer 1 sampai 20 agustus",
            "--jid",
            "628123456789@s.whatsapp.net",
            "--channel",
            "dm",
        ]
    )

    assert exit_code == 0
    assert "cuma jalan di grup" in capsys.readouterr().out
