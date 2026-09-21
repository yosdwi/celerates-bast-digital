from __future__ import annotations

from datetime import date

import anyio
import pytest

import digital_bast.cli as cli_module
from digital_bast.bot import group_entry
from digital_bast.bot.group_entry import GroupQuery, _interpret, _legacy_command, _status_reply
from digital_bast.domain.completion import (
    CheckResult,
    CheckState,
    CompletionReport,
    DateRange,
    EmployeeCompletion,
)
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole


def _check(state: CheckState, *issues: str) -> CheckResult:
    return CheckResult(state, issues)


def _completion(
    employee_id: str,
    name: str,
    *,
    task: CheckState = CheckState.COMPLETE,
    task_issues: tuple[str, ...] = (),
) -> EmployeeCompletion:
    complete = _check(CheckState.COMPLETE)
    return EmployeeCompletion(
        employee_id=employee_id,
        name=name,
        timesheet=complete,
        task_list=_check(task, *task_issues),
        evidence=complete,
        log_1_pama=complete,
        total_tasks=2,
    )


def test_default_group_period_uses_previous_month_during_closeout_week() -> None:
    assert group_entry.default_group_period(date(2026, 9, 1)) == DateRange(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    assert group_entry.default_group_period(date(2026, 9, 7)) == DateRange(
        date(2026, 8, 1), date(2026, 8, 31)
    )


def test_default_group_period_uses_month_to_date_after_closeout_week() -> None:
    assert group_entry.default_group_period(date(2026, 9, 8)) == DateRange(
        date(2026, 9, 1), date(2026, 9, 8)
    )


class _FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.system_prompt = ""
        self.user_prompt = ""

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.response


@pytest.mark.asyncio
async def test_screenshot_phrase_resolves_to_iot_task_status_without_keyword_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        '{"kind":"status","dimension":"task","scope":"iot","employee":null,'
        '"start_date":null,"end_date":null}'
    )
    monkeypatch.setattr(group_entry, "_client", lambda: client)

    query = await _interpret(
        "@conform Conform aku Mau cek status tasklist iot",
        date(2026, 9, 1),
    )

    assert query == GroupQuery(
        "task",
        "iot",
        DateRange(date(2026, 8, 1), date(2026, 8, 31)),
    )
    assert "MAKSUD SELURUH KALIMAT" in client.system_prompt
    assert "tasklist iot" in client.user_prompt


def test_only_explicit_operational_commands_bypass_group_natural_query() -> None:
    assert _legacy_command("@conform export attendance developer 1 sampai 31 agustus") is True
    assert _legacy_command("@conform generate bast 1 sampai 31 agustus") is True
    assert _legacy_command("@conform system status") is True
    assert _legacy_command("@conform aku mau cek status tasklist iot") is False
    assert _legacy_command("@conform siapa yang evidence-nya kurang?") is False


@pytest.mark.asyncio
async def test_legacy_command_runs_bot_reply_without_nesting_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reply() already runs inside an event loop (group_entry.main() drives it
    via anyio.run). bot_reply() is sync and internally calls anyio.run() of
    its own for its business logic -- calling it directly from here would
    nest anyio.run() inside a running loop and raise "Already running
    asyncio in this thread" (the exact bug this regression-tests against).
    """
    calls: list[str] = []

    async def _inner() -> str:
        return "export attendance ready"

    def fake_bot_reply(text: str, *, jid: str | None = None, channel: str = "group") -> str:
        assert jid is None
        assert channel == "group"
        calls.append(text)
        # Real bot_reply() spins up its own event loop for its async
        # business logic (LLM interpret, export, ...) -- reproduce that
        # here so this test actually exercises the nested-loop hazard,
        # not just the plumbing around a plain sync stub.
        return anyio.run(_inner)

    monkeypatch.setattr(cli_module, "bot_reply", fake_bot_reply)

    result = await group_entry.reply("@conform export attendance developer 1 sampai 31 agustus")

    assert result == "export attendance ready"
    assert calls == ["@conform export attendance developer 1 sampai 31 agustus"]


@pytest.mark.asyncio
async def test_iot_scope_filters_completion_by_authoritative_employee_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 31))
    report = CompletionReport(
        period,
        (
            _completion(
                "iot-1",
                "Putra Tama",
                task=CheckState.INCOMPLETE,
                task_issues=("Task A belum Closed.",),
            ),
            _completion(
                "dev-1",
                "Developer Satu",
                task=CheckState.INCOMPLETE,
                task_issues=("Task B belum Closed.",),
            ),
            _completion("iot-2", "IoT Lengkap"),
        ),
    )
    roster = (
        Employee(
            EmployeeId("iot-1"),
            "NRP-IOT-1",
            "Putra Tama",
            EmployeeRole.IOT_OPERATIONS,
        ),
        Employee(
            EmployeeId("dev-1"),
            "NRP-DEV-1",
            "Developer Satu",
            EmployeeRole.DEVELOPER,
        ),
        Employee(
            EmployeeId("iot-2"),
            "NRP-IOT-2",
            "IoT Lengkap",
            EmployeeRole.IOT_OPERATIONS,
        ),
    )

    async def fake_completion_status(
        requested: DateRange,
        employee: str | None = None,
    ) -> CompletionReport:
        assert requested == period
        assert employee is None
        return report

    async def fake_load_roster() -> tuple[Employee, ...]:
        return roster

    monkeypatch.setattr(group_entry, "completion_status", fake_completion_status)
    monkeypatch.setattr(group_entry, "load_roster", fake_load_roster)

    reply = await _status_reply(GroupQuery("task", "iot", period))

    assert reply.startswith("*Task List — IoT Operations — 1-31 Agustus 2026*")
    assert "Lengkap        : 1/2" in reply
    assert "Perlu follow-up: 1" in reply
    assert "Putra Tama" in reply
    assert "Developer Satu" not in reply


@pytest.mark.asyncio
async def test_employee_filter_is_applied_after_role_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 31))
    report = CompletionReport(
        period,
        (
            _completion(
                "iot-1",
                "Putra Tama",
                task=CheckState.INCOMPLETE,
                task_issues=("x",),
            ),
            _completion(
                "dev-1",
                "Putra Developer",
                task=CheckState.INCOMPLETE,
                task_issues=("x",),
            ),
        ),
    )
    roster = (
        Employee(EmployeeId("iot-1"), "I1", "Putra Tama", EmployeeRole.IOT_OPERATIONS),
        Employee(EmployeeId("dev-1"), "D1", "Putra Developer", EmployeeRole.DEVELOPER),
    )

    async def fake_completion_status(
        requested: DateRange,
        employee: str | None = None,
    ) -> CompletionReport:
        return report

    async def fake_load_roster() -> tuple[Employee, ...]:
        return roster

    monkeypatch.setattr(group_entry, "completion_status", fake_completion_status)
    monkeypatch.setattr(group_entry, "load_roster", fake_load_roster)

    reply = await _status_reply(GroupQuery("task", "iot", period, "Putra"))

    assert "Putra Tama" in reply
    assert "Putra Developer" not in reply
