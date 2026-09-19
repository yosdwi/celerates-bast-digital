from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_read import PayrollDayView
from digital_bast.bot import dm_entry
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderGapSelection,
    AttendanceReminderRouteResult,
    AttendanceReminderRouteStatus,
)

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_CYCLE = payroll_cycle(2026, 9)


class _DraftState:
    def __init__(self) -> None:
        self.begun: list[tuple[str, str, str]] = []

    async def pending(self, jid: str) -> None:
        assert jid == _JID
        return None

    async def begin(self, jid: str, employee_id: str, attendance_key: str) -> object:
        self.begun.append((jid, employee_id, attendance_key))
        return object()


class _Activation:
    async def resolve(self, jid: str) -> str:
        assert jid == _JID
        return _EMPLOYEE_ID


class _ReminderContextStore:
    def __init__(self, context: AttendanceReminderContext | None) -> None:
        self.context = context
        self.cleared = 0

    async def load(self, jid: str) -> AttendanceReminderContext | None:
        assert jid == _JID
        return self.context

    async def clear(self, jid: str) -> None:
        assert jid == _JID
        self.cleared += 1


class _EvidenceSelection:
    def __init__(self, active_kind: str | None = None) -> None:
        self.value = active_kind

    async def active_kind(self, jid: str) -> str | None:
        assert jid == _JID
        return self.value


class _Routing:
    def __init__(self, result: AttendanceReminderRouteResult) -> None:
        self.result = result
        self.calls = 0

    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        assert context.employee_id == _EMPLOYEE_ID
        assert employee_id == _EMPLOYEE_ID
        assert now.tzinfo is not None
        self.calls += 1
        return self.result


def _context() -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        _EMPLOYEE_ID,
        _CYCLE.cycle_id,
        ("attendance:four", "attendance:seven"),
        _NOW + timedelta(days=2),
    )


def _selection() -> AttendanceReminderGapSelection:
    day = PayrollDayView(
        attendance_id=4,
        attendance_key="attendance:four",
        work_date=date(2026, 9, 4),
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in="07:32",
        raw_check_out=None,
        proposed_check_in=None,
        proposed_check_out=None,
        resolution_id=None,
        resolution_status=None,
        resolution_type=None,
        absence_type=None,
        rejection_reason=None,
        has_evidence=False,
        status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
        reason=AttendanceClosingReason.GAP_UNCOVERED,
        talent_action_required=True,
    )
    return AttendanceReminderGapSelection(_CYCLE, day, 2)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    context: AttendanceReminderContext | None = None,
    active_kind: str | None = None,
    route_status: AttendanceReminderRouteStatus = AttendanceReminderRouteStatus.OPEN,
) -> tuple[_ReminderContextStore, _Routing, _DraftState]:
    store = _ReminderContextStore(context if context is not None else _context())
    selection = _selection() if route_status is AttendanceReminderRouteStatus.OPEN else None
    routing = _Routing(AttendanceReminderRouteResult(route_status, selection))
    draft_state = _DraftState()
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: draft_state,
    )
    monkeypatch.setattr(dm_entry, "create_activation_service", lambda: _Activation())
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_reminder_context_service",
        lambda: store,
    )
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_reminder_routing_service",
        lambda: routing,
    )
    monkeypatch.setattr(
        dm_entry,
        "create_evidence_service",
        lambda: _EvidenceSelection(active_kind),
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(dm_entry.anyio, "sleep", no_sleep)
    return store, routing, draft_state


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["payroll_attendance_start", "lengkapi", "1"])
async def test_payroll_start_opens_current_gap_without_mobile(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    _, routing, draft_state = _patch(monkeypatch)

    def mobile_should_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("Payroll reminder happy path must not open Talent Mobile")

    monkeypatch.setattr(dm_entry, "configured_talent_mobile_url", mobile_should_not_run)

    response = await dm_entry.reply(message, _JID)

    assert "4 September" in response
    assert "Clock In tercatat 07:32" in response
    assert "Jam pulang berapa?" in response
    assert "Masih ada 1 tanggal setelah ini" in response
    assert routing.calls == 1
    assert draft_state.begun == [(_JID, _EMPLOYEE_ID, "attendance:four")]


@pytest.mark.asyncio
async def test_payroll_later_keeps_snapshot_and_does_not_route_or_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, routing, draft_state = _patch(monkeypatch)

    response = await dm_entry.reply("2", _JID)

    assert "belum ada data attendance yang diubah" in response
    assert "lengkapi" in response
    assert store.cleared == 0
    assert routing.calls == 0
    assert draft_state.begun == []


@pytest.mark.asyncio
async def test_no_longer_actionable_snapshot_is_cleared_without_mobile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, routing, draft_state = _patch(
        monkeypatch,
        route_status=AttendanceReminderRouteStatus.NO_ACTION,
    )

    response = await dm_entry.reply("lengkapi", _JID)

    assert "sudah tidak perlu action" in response
    assert store.cleared == 1
    assert routing.calls == 1
    assert draft_state.begun == []


@pytest.mark.asyncio
async def test_legacy_active_evidence_selection_wins_over_payroll_digit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, routing, draft_state = _patch(monkeypatch, active_kind="attendance")

    async def legacy(text: str, jid: str) -> str:
        assert text == "1"
        assert jid == _JID
        return "LEGACY PICK"

    monkeypatch.setattr(dm_entry, "workflow_reply", legacy)

    response = await dm_entry.reply("1", _JID)

    assert response == "LEGACY PICK"
    assert routing.calls == 0
    assert draft_state.begun == []
