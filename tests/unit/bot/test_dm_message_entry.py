from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from digital_bast.bot import dm_message_entry
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderRouteResult,
    AttendanceReminderRouteStatus,
)
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.payroll_attendance_natural import PayrollAttendanceCandidate

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_ATTENDANCE_KEY = "ATT-2026-09-07"
_MESSAGE_AT = datetime(2026, 9, 8, 1, 30, tzinfo=UTC)


class _State:
    def __init__(self, resolution_type: ResolutionType = ResolutionType.MISSING_CLOCK_OUT) -> None:
        self.draft = AttendanceResolutionDraft(
            attendance_key=_ATTENDANCE_KEY,
            employee_id=_EMPLOYEE_ID,
            resolution_type=resolution_type,
            work_date=date(2026, 9, 7),
            has_evidence=False,
        )
        self.saved: list[dict[str, object]] = []
        self.cleared = False

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        return self.draft

    async def save_proposal(self, wa_jid: str, employee_id: str, attendance_key: str, resolution_type: ResolutionType, **kwargs: object) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        assert attendance_key == _ATTENDANCE_KEY
        self.saved.append({"resolution_type": resolution_type, **kwargs})
        self.draft = replace(
            self.draft,
            resolution_type=resolution_type,
            proposed_check_in=kwargs.get("proposed_check_in"),
            proposed_check_out=kwargs.get("proposed_check_out"),
            absence_type=kwargs.get("absence_type"),
        )
        return self.draft

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True


class _ContextStore:
    def __init__(self) -> None:
        self.context = AttendanceReminderContext.create(
            employee_id=_EMPLOYEE_ID,
            cycle_id="2026-09:2026-08-21:2026-09-20",
            attendance_keys=(_ATTENDANCE_KEY,),
            expires_at=_MESSAGE_AT + timedelta(days=2),
        )

    async def load(self, wa_jid: str) -> AttendanceReminderContext:
        assert wa_jid == _JID
        return self.context


class _Routing:
    async def first_actionable(self, context: object, *, employee_id: str, now: datetime) -> AttendanceReminderRouteResult:
        assert context is not None
        assert employee_id == _EMPLOYEE_ID
        assert now.tzinfo is not None
        selection = SimpleNamespace(day=SimpleNamespace(attendance_key=_ATTENDANCE_KEY))
        return AttendanceReminderRouteResult(AttendanceReminderRouteStatus.OPEN, selection)


class _Interpreter:
    def __init__(self, candidate: PayrollAttendanceCandidate | None) -> None:
        self.candidate = candidate
        self.calls: list[dict[str, object]] = []

    async def interpret(self, text: str, **kwargs: object) -> PayrollAttendanceCandidate | None:
        self.calls.append({"text": text, **kwargs})
        return self.candidate


def _wire(monkeypatch: pytest.MonkeyPatch, state: _State, interpreter: _Interpreter | None = None) -> list[tuple[str, str]]:
    context = _ContextStore()
    delegated: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dm_message_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: state,
    )
    monkeypatch.setattr(
        dm_message_entry,
        "create_attendance_reminder_context_service",
        lambda: context,
    )
    monkeypatch.setattr(
        dm_message_entry,
        "create_attendance_reminder_routing_service",
        _Routing,
    )
    monkeypatch.setattr(
        dm_message_entry,
        "create_payroll_attendance_natural_interpreter",
        lambda: interpreter,
    )

    async def workflow(text: str, jid: str) -> str:
        delegated.append((text, jid))
        return "DELEGATED"

    monkeypatch.setattr(dm_message_entry, "workflow_reply", workflow)
    return delegated


async def test_explicit_kemarin_clock_out_saves_only_current_exact_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _State()
    delegated = _wire(monkeypatch, state)

    response = await dm_message_entry.reply("jam pulang kemarin 17.40", _JID, _MESSAGE_AT)

    assert "sudah tersimpan" in response
    assert delegated == []
    assert len(state.saved) == 1
    assert state.saved[0]["resolution_type"] is ResolutionType.MISSING_CLOCK_OUT
    assert state.saved[0]["proposed_check_out"] == time(17, 40)


async def test_explicit_wrong_date_does_not_mutate_or_switch_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _State()
    delegated = _wire(monkeypatch, state)

    response = await dm_message_entry.reply("tanggal 8 jam pulang 17.40", _JID, _MESSAGE_AT)

    assert "belum menyimpan perubahan" in response
    assert "7 September" in response
    assert state.saved == []
    assert delegated == []


async def test_numeric_same_gap_action_keeps_existing_parser_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _State()
    delegated = _wire(monkeypatch, state)

    response = await dm_message_entry.reply("1", _JID, _MESSAGE_AT)

    assert response == "DELEGATED"
    assert delegated == [("1", _JID)]
    assert state.saved == []


async def test_natural_textual_time_candidate_revalidates_then_saves(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _State()
    interpreter = _Interpreter(
        PayrollAttendanceCandidate(
            work_date=date(2026, 9, 7),
            resolution_type=ResolutionType.MISSING_CLOCK_OUT,
            proposed_check_out=time(17, 0),
        )
    )
    delegated = _wire(monkeypatch, state, interpreter)

    response = await dm_message_entry.reply(
        "kemarin aku pulang jam lima sore",
        _JID,
        _MESSAGE_AT,
    )

    assert "sudah tersimpan" in response
    assert delegated == []
    assert interpreter.calls[0]["message_at"] == _MESSAGE_AT
    assert state.saved[0]["proposed_check_out"] == time(17, 0)


async def test_natural_candidate_for_other_date_is_rejected_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _State()
    interpreter = _Interpreter(
        PayrollAttendanceCandidate(
            work_date=date(2026, 9, 6),
            resolution_type=ResolutionType.MISSING_CLOCK_OUT,
            proposed_check_out=time(17, 0),
        )
    )
    delegated = _wire(monkeypatch, state, interpreter)

    response = await dm_message_entry.reply("hari itu pulang jam lima sore", _JID, _MESSAGE_AT)

    assert "belum menyimpan perubahan" in response
    assert state.saved == []
    assert delegated == []


async def test_ambiguous_missing_both_natural_reply_does_not_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _State(ResolutionType.MISSING_BOTH_WORKED)
    interpreter = _Interpreter(None)
    delegated = _wire(monkeypatch, state, interpreter)

    response = await dm_message_entry.reply("kemarin kerja seperti biasa", _JID, _MESSAGE_AT)

    assert response == "DELEGATED"
    assert state.saved == []
    assert delegated == [("kemarin kerja seperti biasa", _JID)]
