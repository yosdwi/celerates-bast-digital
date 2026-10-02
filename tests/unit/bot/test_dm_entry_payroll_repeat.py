from datetime import UTC, date, datetime, time, timedelta

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
    AttendanceSameGapSuggestion,
)
from digital_bast.bot.payroll_attendance_repeat import (
    PAYROLL_REPEAT_DIFFERENT_ACTION_ID,
    PAYROLL_REPEAT_SAME_ACTION_ID,
)

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_CYCLE = payroll_cycle(2026, 9)
_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)


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


class _ContextStore:
    def __init__(self, context: AttendanceReminderContext) -> None:
        self.context = context

    async def load(self, jid: str) -> AttendanceReminderContext:
        assert jid == _JID
        return self.context

    async def clear(self, jid: str) -> None:
        raise AssertionError("eligible same-gap continuation must keep context")


class _EvidenceSelection:
    async def active_kind(self, jid: str) -> None:
        assert jid == _JID
        return None


class _Routing:
    def __init__(self, selection: AttendanceReminderGapSelection) -> None:
        self.selection = selection

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
        return AttendanceReminderRouteResult(
            AttendanceReminderRouteStatus.OPEN,
            self.selection,
        )


def _context() -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        employee_id=_EMPLOYEE_ID,
        cycle_id=_CYCLE.cycle_id,
        attendance_keys=("attendance:four", "attendance:seven"),
        expires_at=_NOW + timedelta(days=2),
    )


def _selection() -> AttendanceReminderGapSelection:
    day = PayrollDayView(
        attendance_id=7,
        attendance_key="attendance:seven",
        work_date=date(2026, 9, 7),
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in="07:28",
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
    suggestion = AttendanceSameGapSuggestion(
        source_work_date=date(2026, 9, 4),
        resolution_type="missing_clock_out",
        proposed_check_out=time(17, 40),
    )
    return AttendanceReminderGapSelection(_CYCLE, day, 1, suggestion)


@pytest.mark.asyncio
async def test_continue_opens_same_or_different_prompt_before_copying_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _DraftState()
    context = _context()
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_resolution_dm_state_service",
        lambda: state,
    )
    monkeypatch.setattr(dm_entry, "create_activation_service", _Activation)
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_reminder_context_service",
        lambda: _ContextStore(context),
    )
    monkeypatch.setattr(
        dm_entry,
        "create_attendance_reminder_routing_service",
        lambda: _Routing(_selection()),
    )
    monkeypatch.setattr(dm_entry, "create_evidence_service", _EvidenceSelection)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(dm_entry.anyio, "sleep", no_sleep)

    response = await dm_entry.reply("lanjut", _JID)

    assert state.begun == [(_JID, _EMPLOYEE_ID, "attendance:seven")]
    assert "7 September" in response
    assert "4 September" in response
    assert "Clock Out 17:40" in response
    assert "jam pulangnya sama" in response
    assert PAYROLL_REPEAT_SAME_ACTION_ID in response
    assert PAYROLL_REPEAT_DIFFERENT_ACTION_ID in response
    assert "Ajukan" not in response
