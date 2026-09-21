from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

from digital_bast.bot import dm_message_entry
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderRouteResult,
    AttendanceReminderRouteStatus,
)
from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.payroll_attendance_natural import PayrollAttendanceCandidate

if TYPE_CHECKING:
    import pytest

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_ATTENDANCE_KEY = "ATT-2026-09-07"
_MESSAGE_AT = datetime(2026, 9, 8, 1, 30, tzinfo=UTC)


class _State:
    def __init__(
        self,
        resolution_type: ResolutionType = ResolutionType.MISSING_CLOCK_OUT,
        *,
        active: bool = True,
    ) -> None:
        self.draft: AttendanceResolutionDraft | None = (
            AttendanceResolutionDraft(
                attendance_key=_ATTENDANCE_KEY,
                employee_id=_EMPLOYEE_ID,
                resolution_type=resolution_type,
                work_date=date(2026, 9, 7),
                has_evidence=False,
            )
            if active
            else None
        )
        self.saved: list[dict[str, object]] = []
        self.begun: list[tuple[str, str, str]] = []
        self.cleared = False

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft | None:
        assert wa_jid == _JID
        return self.draft

    async def begin(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        self.begun.append((wa_jid, employee_id, attendance_key))
        work_date = {
            "ATT-2026-09-01": date(2026, 9, 1),
            "ATT-2026-09-07": date(2026, 9, 7),
            "ATT-2026-09-15": date(2026, 9, 15),
        }[attendance_key]
        self.draft = AttendanceResolutionDraft(
            attendance_key=attendance_key,
            employee_id=employee_id,
            resolution_type=ResolutionType.MISSING_BOTH_WORKED,
            work_date=work_date,
            has_evidence=False,
        )
        return self.draft

    async def save_proposal(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        **kwargs: object,
    ) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        assert self.draft is not None
        assert attendance_key == self.draft.attendance_key
        self.saved.append(
            {
                "attendance_key": attendance_key,
                "resolution_type": resolution_type,
                **kwargs,
            }
        )
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


class _Activation:
    async def resolve(self, jid: str) -> str:
        assert jid == _JID
        return _EMPLOYEE_ID


class _ContextStore:
    def __init__(self, keys: tuple[str, ...]) -> None:
        self.context = AttendanceReminderContext.create(
            employee_id=_EMPLOYEE_ID,
            cycle_id="2026-09:2026-08-21:2026-09-20",
            attendance_keys=keys,
            expires_at=_MESSAGE_AT + timedelta(days=20),
        )
        self.cleared = False

    async def load(self, wa_jid: str) -> AttendanceReminderContext:
        assert wa_jid == _JID
        return self.context

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True


class _Routing:
    def __init__(self, by_date: dict[date, str]) -> None:
        self.by_date = by_date
        self.exact_calls: list[date] = []

    async def actionable_on(
        self,
        context: object,
        *,
        employee_id: str,
        work_date: date,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        assert context is not None
        assert employee_id == _EMPLOYEE_ID
        assert now.tzinfo is not None
        self.exact_calls.append(work_date)
        key = self.by_date.get(work_date)
        if key is None:
            return AttendanceReminderRouteResult(AttendanceReminderRouteStatus.NO_ACTION)
        selection = SimpleNamespace(day=SimpleNamespace(attendance_key=key, work_date=work_date))
        return AttendanceReminderRouteResult(AttendanceReminderRouteStatus.OPEN, selection)


class _Interpreter:
    def __init__(self, candidate: PayrollAttendanceCandidate | None) -> None:
        self.candidate = candidate
        self.calls: list[dict[str, object]] = []

    async def interpret(self, text: str, **kwargs: object) -> PayrollAttendanceCandidate | None:
        self.calls.append({"text": text, **kwargs})
        return self.candidate


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    state: _State,
    interpreter: _Interpreter | None = None,
    *,
    keys: tuple[str, ...] = (_ATTENDANCE_KEY,),
    by_date: dict[date, str] | None = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], _Routing]:
    context = _ContextStore(keys)
    routing = _Routing(by_date or {date(2026, 9, 7): _ATTENDANCE_KEY})
    delegated: list[tuple[str, str]] = []
    legacy: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dm_message_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: state,
    )
    monkeypatch.setattr(dm_message_entry, "create_activation_service", _Activation)
    monkeypatch.setattr(
        dm_message_entry,
        "create_attendance_reminder_context_service",
        lambda: context,
    )
    monkeypatch.setattr(
        dm_message_entry,
        "create_attendance_reminder_routing_service",
        lambda: routing,
    )
    monkeypatch.setattr(
        dm_message_entry,
        "create_payroll_attendance_natural_interpreter",
        lambda: interpreter,
    )

    async def workflow(text: str, jid: str) -> str:
        delegated.append((text, jid))
        return "DELEGATED"

    async def legacy_reply(text: str, jid: str) -> str:
        legacy.append((text, jid))
        return "LEGACY"

    monkeypatch.setattr(dm_message_entry, "workflow_reply", workflow)
    monkeypatch.setattr(dm_message_entry, "legacy_entry_reply", legacy_reply)
    return delegated, legacy, routing


async def test_explicit_kemarin_clock_out_saves_only_current_exact_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    delegated, _, _ = _wire(monkeypatch, state)

    response = await dm_message_entry.reply("jam pulang kemarin 17.40", _JID, _MESSAGE_AT)

    assert "sudah tersimpan" in response
    assert delegated == []
    assert len(state.saved) == 1
    assert state.saved[0]["resolution_type"] is ResolutionType.MISSING_CLOCK_OUT
    assert state.saved[0]["proposed_check_out"] == time(17, 40)


async def test_explicit_wrong_date_does_not_mutate_or_switch_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    delegated, _, _ = _wire(monkeypatch, state)

    response = await dm_message_entry.reply("tanggal 8 jam pulang 17.40", _JID, _MESSAGE_AT)

    assert "belum menyimpan perubahan" in response
    assert "7 September" in response
    assert state.saved == []
    assert delegated == []


async def test_numeric_same_gap_action_keeps_existing_parser_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    delegated, _, _ = _wire(monkeypatch, state)

    response = await dm_message_entry.reply("1", _JID, _MESSAGE_AT)

    assert response == "DELEGATED"
    assert delegated == [("1", _JID)]
    assert state.saved == []


async def test_natural_textual_time_candidate_revalidates_then_saves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    interpreter = _Interpreter(
        PayrollAttendanceCandidate(
            work_date=date(2026, 9, 7),
            resolution_type=ResolutionType.MISSING_CLOCK_OUT,
            proposed_check_out=time(17, 0),
        )
    )
    delegated, _, _ = _wire(monkeypatch, state, interpreter)

    response = await dm_message_entry.reply(
        "kemarin aku pulang jam lima sore",
        _JID,
        _MESSAGE_AT,
    )

    assert "sudah tersimpan" in response
    assert delegated == []
    assert interpreter.calls[0]["message_at"] == _MESSAGE_AT
    assert state.saved[0]["proposed_check_out"] == time(17, 0)


async def test_natural_candidate_for_other_date_is_rejected_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    interpreter = _Interpreter(
        PayrollAttendanceCandidate(
            work_date=date(2026, 9, 6),
            resolution_type=ResolutionType.MISSING_CLOCK_OUT,
            proposed_check_out=time(17, 0),
        )
    )
    delegated, _, _ = _wire(monkeypatch, state, interpreter)

    response = await dm_message_entry.reply("hari itu pulang jam lima sore", _JID, _MESSAGE_AT)

    assert "belum menyimpan perubahan" in response
    assert state.saved == []
    assert delegated == []


async def test_ambiguous_missing_both_natural_reply_does_not_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(ResolutionType.MISSING_BOTH_WORKED)
    interpreter = _Interpreter(None)
    delegated, _, _ = _wire(monkeypatch, state, interpreter)

    response = await dm_message_entry.reply("kemarin kerja seperti biasa", _JID, _MESSAGE_AT)

    assert response == "DELEGATED"
    assert state.saved == []
    assert delegated == [("kemarin kerja seperti biasa", _JID)]


async def test_direct_cuti_sentence_bootstraps_exact_gap_without_mobile_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(active=False)
    keys = ("ATT-2026-09-01", "ATT-2026-09-15")
    delegated, legacy, routing = _wire(
        monkeypatch,
        state,
        keys=keys,
        by_date={
            date(2026, 9, 1): "ATT-2026-09-01",
            date(2026, 9, 15): "ATT-2026-09-15",
        },
    )
    message_at = datetime(2026, 9, 21, 8, 1, tzinfo=UTC)

    response = await dm_message_entry.reply(
        "aku tanggal 1 september itu cuti tahunan",
        _JID,
        message_at,
    )

    assert delegated == []
    assert legacy == []
    assert routing.exact_calls == [date(2026, 9, 1), date(2026, 9, 1)]
    assert state.begun == [(_JID, _EMPLOYEE_ID, "ATT-2026-09-01")]
    assert len(state.saved) == 1
    assert state.saved[0]["attendance_key"] == "ATT-2026-09-01"
    assert state.saved[0]["resolution_type"] is ResolutionType.ABSENCE
    assert state.saved[0]["absence_type"] is AbsenceType.CUTI
    assert "sudah tersimpan" in response
    assert "1 September" in response
    assert "Status: Cuti" in response
    assert "kirim screenshot/bukti attendance" in response


async def test_date_action_opens_exact_missing_both_gap_with_presence_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(active=False)
    _, legacy, _ = _wire(
        monkeypatch,
        state,
        keys=("ATT-2026-09-01", "ATT-2026-09-15"),
        by_date={
            date(2026, 9, 1): "ATT-2026-09-01",
            date(2026, 9, 15): "ATT-2026-09-15",
        },
    )

    response = await dm_message_entry.reply(
        "payroll_attendance_date:2026-09-15",
        _JID,
        datetime(2026, 9, 21, 8, 1, tzinfo=UTC),
    )
    payload = json.loads(response)

    assert legacy == []
    assert state.begun == [(_JID, _EMPLOYEE_ID, "ATT-2026-09-15")]
    assert state.saved == []
    assert "15 September" in payload["text"]
    assert [action["label"] for action in payload["actions"]] == [
        "Masuk kerja",
        "Tidak masuk",
    ]


async def test_direct_second_gap_worked_sentence_is_not_blocked_by_first_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(active=False)
    _wire(
        monkeypatch,
        state,
        keys=("ATT-2026-09-01", "ATT-2026-09-15"),
        by_date={
            date(2026, 9, 1): "ATT-2026-09-01",
            date(2026, 9, 15): "ATT-2026-09-15",
        },
    )

    response = await dm_message_entry.reply(
        "15 September masuk 07:30 pulang 17:00",
        _JID,
        datetime(2026, 9, 21, 8, 1, tzinfo=UTC),
    )

    assert state.begun == [(_JID, _EMPLOYEE_ID, "ATT-2026-09-15")]
    assert state.saved[0]["attendance_key"] == "ATT-2026-09-15"
    assert state.saved[0]["resolution_type"] is ResolutionType.MISSING_BOTH_WORKED
    assert state.saved[0]["proposed_check_in"] == time(7, 30)
    assert state.saved[0]["proposed_check_out"] == time(17, 0)
    assert "15 September" in response
    assert "kirim screenshot/bukti attendance" in response


async def test_natural_absence_without_date_asks_which_gap_instead_of_mobile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(active=False)
    delegated, legacy, _ = _wire(
        monkeypatch,
        state,
        keys=("ATT-2026-09-01", "ATT-2026-09-15"),
        by_date={
            date(2026, 9, 1): "ATT-2026-09-01",
            date(2026, 9, 15): "ATT-2026-09-15",
        },
    )

    response = await dm_message_entry.reply(
        "aku cuti",
        _JID,
        datetime(2026, 9, 21, 8, 1, tzinfo=UTC),
    )

    assert delegated == []
    assert legacy == []
    assert state.begun == []
    assert state.saved == []
    assert "untuk attendance yang mana" in response
    assert "1 September cuti" in response


async def test_date_outside_active_reminder_fails_closed_without_opening_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(active=False)
    _, legacy, _ = _wire(
        monkeypatch,
        state,
        keys=("ATT-2026-09-01", "ATT-2026-09-15"),
        by_date={
            date(2026, 9, 1): "ATT-2026-09-01",
            date(2026, 9, 15): "ATT-2026-09-15",
        },
    )

    response = await dm_message_entry.reply(
        "20 September cuti",
        _JID,
        datetime(2026, 9, 21, 8, 1, tzinfo=UTC),
    )

    assert legacy == []
    assert state.begun == []
    assert state.saved == []
    assert "tidak termasuk attendance yang masih perlu action" in response
