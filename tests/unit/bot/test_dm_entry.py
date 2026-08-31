from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from digital_bast.bot import dm_entry
from digital_bast.bot.talent_context import (
    TalentConversationContext,
    TalentIntent,
    TalentInterpretation,
)
from digital_bast.domain.completion import CheckResult, CheckState, DateRange, EmployeeCompletion

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_CURRENT = DateRange(date(2026, 9, 1), date(2026, 9, 1))
_AUGUST = DateRange(date(2026, 8, 1), date(2026, 8, 31))


class _DraftState:
    def __init__(self, pending: object | None = None) -> None:
        self.value = pending

    async def pending(self, jid: str) -> object | None:
        assert jid == _JID
        return self.value


class _Activation:
    async def resolve(self, jid: str) -> str | None:
        assert jid == _JID
        return _EMPLOYEE_ID


class _ContextStore:
    def __init__(self, loaded: TalentConversationContext | None = None) -> None:
        self.loaded = loaded
        self.saved: list[TalentConversationContext] = []

    async def load(self, jid: str) -> TalentConversationContext | None:
        assert jid == _JID
        return self.loaded

    async def save(self, jid: str, context: TalentConversationContext) -> None:
        assert jid == _JID
        self.saved.append(context)


class _Interpreter:
    def __init__(self, result: TalentInterpretation | None) -> None:
        self.result = result
        self.calls: list[tuple[str, date, TalentConversationContext | None]] = []

    async def interpret_talent(
        self,
        text: str,
        today: date,
        context: TalentConversationContext | None = None,
    ) -> TalentInterpretation | None:
        self.calls.append((text, today, context))
        return self.result


class _ResolutionService:
    async def for_employee(self, employee_id: str) -> tuple[object, ...]:
        assert employee_id == _EMPLOYEE_ID
        return ()


class _EvidenceService:
    async def list_candidates(self, employee_id: str) -> tuple[object, ...]:
        assert employee_id == _EMPLOYEE_ID
        return ()


def _employee() -> EmployeeCompletion:
    ok = CheckResult(CheckState.COMPLETE, ())
    return EmployeeCompletion(
        employee_id=_EMPLOYEE_ID,
        name="Putra Tama",
        timesheet=ok,
        task_list=ok,
        evidence=ok,
        log_1_pama=ok,
        total_work_days=1,
    )


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: _ContextStore | None = None,
    interpreter: _Interpreter | None = None,
) -> _ContextStore:
    active_store = store or _ContextStore()
    monkeypatch.setattr(dm_entry, "_period_now", lambda: _CURRENT)
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: _DraftState(),
    )
    monkeypatch.setattr(dm_entry, "create_activation_service", lambda: _Activation())
    monkeypatch.setattr(
        dm_entry,
        "create_talent_conversation_context_service",
        lambda: active_store,
    )
    monkeypatch.setattr(dm_entry, "create_attendance_resolution_service", lambda: _ResolutionService())
    monkeypatch.setattr(dm_entry, "create_evidence_service", lambda: _EvidenceService())
    monkeypatch.setattr(dm_entry, "create_llm_interpreter", lambda: interpreter)

    async def completion(_period: DateRange) -> object:
        return SimpleNamespace(employees=(_employee(),))

    async def public_url() -> str:
        return "https://conform.example"

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(dm_entry, "completion_status", completion)
    monkeypatch.setattr(dm_entry, "_saved_public_url", public_url)
    monkeypatch.setattr(dm_entry.anyio, "sleep", no_sleep)
    return active_store


@pytest.mark.asyncio
async def test_exact_attendance_is_fast_path_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _patch_common(monkeypatch, interpreter=None)
    seen_periods: list[DateRange] = []

    def mobile_url(
        employee_id: str,
        jid: str,
        period: DateRange,
        tab: str,
        *,
        public_url: str | None = None,
    ) -> str:
        assert employee_id == _EMPLOYEE_ID
        assert jid == _JID
        assert tab == "attendance"
        assert public_url == "https://conform.example"
        seen_periods.append(period)
        return "https://conform.example/talent/mobile?tab=attendance"

    monkeypatch.setattr(dm_entry, "configured_talent_mobile_url", mobile_url)

    response = await dm_entry.reply("attendance", _JID)

    assert "Attendance — 1-1 September 2026" in response
    assert seen_periods == [_CURRENT]
    assert store.saved[-1] == TalentConversationContext(TalentIntent.ATTENDANCE, _CURRENT)


@pytest.mark.asyncio
async def test_natural_language_historical_period_flows_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter = _Interpreter(TalentInterpretation(TalentIntent.ATTENDANCE, _AUGUST))
    store = _patch_common(monkeypatch, interpreter=interpreter)
    seen_periods: list[DateRange] = []

    def mobile_url(
        _employee_id: str,
        _jid: str,
        period: DateRange,
        _tab: str,
        *,
        public_url: str | None = None,
    ) -> str:
        assert public_url == "https://conform.example"
        seen_periods.append(period)
        return "https://conform.example/august"

    monkeypatch.setattr(dm_entry, "configured_talent_mobile_url", mobile_url)

    response = await dm_entry.reply("attendance bulan agustus 2026", _JID)

    assert "1-31 Agustus 2026" in response
    assert seen_periods == [_AUGUST]
    assert store.saved[-1] == TalentConversationContext(TalentIntent.ATTENDANCE, _AUGUST)
    assert interpreter.calls[0][0] == "attendance bulan agustus 2026"


@pytest.mark.asyncio
async def test_ambiguous_statement_does_not_fall_back_to_legacy_keyword_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter = _Interpreter(TalentInterpretation(TalentIntent.UNKNOWN))
    _patch_common(monkeypatch, interpreter=interpreter)

    async def legacy_should_not_run(_text: str, _jid: str) -> str:
        raise AssertionError("legacy substring parser must not receive ambiguous bound-Talent text")

    monkeypatch.setattr(dm_entry, "workflow_reply", legacy_should_not_run)

    response = await dm_entry.reply("tasklist kemarin sebenarnya sudah aku isi", _JID)
    payload = json.loads(response)

    assert payload["kind"] == "interactive"
    assert "belum yakin" in payload["text"]
    assert [item["id"] for item in payload["actions"]] == [
        "bast-saya",
        "attendance",
        "tasklist",
    ]


@pytest.mark.asyncio
async def test_followup_context_is_passed_to_natural_language_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = TalentConversationContext(TalentIntent.ATTENDANCE, _AUGUST)
    store = _ContextStore(context)
    interpreter = _Interpreter(TalentInterpretation(TalentIntent.REQUESTS, _AUGUST))
    _patch_common(monkeypatch, store=store, interpreter=interpreter)

    async def request_view(_employee_id: str, period: DateRange | None = None) -> str:
        assert period == _AUGUST
        return "REQUESTS AUGUST"

    monkeypatch.setattr(dm_entry, "talent_requests", request_view)

    response = await dm_entry.reply("yang pending PMO mana?", _JID)

    assert response == "REQUESTS AUGUST"
    assert interpreter.calls[0][2] == context
    assert store.saved[-1] == TalentConversationContext(TalentIntent.REQUESTS, _AUGUST)


@pytest.mark.asyncio
async def test_bare_digit_stays_with_legacy_evidence_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: _DraftState(),
    )

    async def legacy(text: str, jid: str) -> str:
        assert text == "1"
        assert jid == _JID
        return "LEGACY PICK"

    monkeypatch.setattr(dm_entry, "workflow_reply", legacy)

    assert await dm_entry.reply("1", _JID) == "LEGACY PICK"


@pytest.mark.asyncio
async def test_active_attendance_draft_wins_before_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: _DraftState(object()),
    )

    async def legacy(text: str, jid: str) -> str:
        assert text == "attendance"
        assert jid == _JID
        return "RESOLUTION PROMPT"

    monkeypatch.setattr(dm_entry, "workflow_reply", legacy)

    assert await dm_entry.reply("attendance", _JID) == "RESOLUTION PROMPT"
