from datetime import UTC, date, datetime, time, timedelta

import pytest

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_read import (
    PayrollDayView,
    PayrollOverview,
    PayrollSummary,
    PayrollTalentView,
)
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderRouteResult,
    AttendanceReminderRouteStatus,
    AttendanceReminderRoutingService,
)
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.payroll_attendance_repeat import (
    PAYROLL_REPEAT_DIFFERENT_ACTION_ID,
    PAYROLL_REPEAT_SAME_ACTION_ID,
    PayrollRepeatCommand,
    handle_payroll_repeat_command,
    parse_payroll_repeat_command,
    render_payroll_repeat_prompt,
)

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_FIRST_KEY = "ATT-2026-09-04"
_NEXT_KEY = "ATT-2026-09-07"
_CYCLE = payroll_cycle(2026, 9)
_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)


def _day(
    *,
    key: str,
    work_date: date,
    raw_in: str | None,
    raw_out: str | None,
    status: AttendanceClosingStatus,
    reason: AttendanceClosingReason,
    actionable: bool,
    resolution_status: str | None = None,
    resolution_type: str | None = None,
    proposed_in: str | None = None,
    proposed_out: str | None = None,
) -> PayrollDayView:
    return PayrollDayView(
        attendance_id=1 if key == _FIRST_KEY else 2,
        attendance_key=key,
        work_date=work_date,
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in=raw_in,
        raw_check_out=raw_out,
        proposed_check_in=proposed_in,
        proposed_check_out=proposed_out,
        resolution_id="request-1" if resolution_status is not None else None,
        resolution_status=resolution_status,
        resolution_type=resolution_type,
        absence_type=None,
        rejection_reason=None,
        has_evidence=resolution_status is not None,
        status=status,
        reason=reason,
        talent_action_required=actionable,
    )


def _prior_pending_clock_out(*, resolution_status: str = "pending") -> PayrollDayView:
    return _day(
        key=_FIRST_KEY,
        work_date=date(2026, 9, 4),
        raw_in="07:31",
        raw_out=None,
        status=AttendanceClosingStatus.WAITING_SUBMITTED,
        reason=AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST,
        actionable=False,
        resolution_status=resolution_status,
        resolution_type="missing_clock_out",
        proposed_out="17:40",
    )


def _current_missing_clock_out() -> PayrollDayView:
    return _day(
        key=_NEXT_KEY,
        work_date=date(2026, 9, 7),
        raw_in="07:28",
        raw_out=None,
        status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
        reason=AttendanceClosingReason.GAP_UNCOVERED,
        actionable=True,
    )


def _context() -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        employee_id=_EMPLOYEE_ID,
        cycle_id=_CYCLE.cycle_id,
        attendance_keys=(_FIRST_KEY, _NEXT_KEY),
        expires_at=_NOW + timedelta(days=2),
    )


class _Payroll:
    def __init__(self, *days: PayrollDayView) -> None:
        self.days = days

    async def overview(self, cycle: object, *, now: datetime) -> PayrollOverview:
        assert cycle == _CYCLE
        assert now == _NOW
        actionable = sum(day.talent_action_required for day in self.days)
        waiting = sum(day.status is AttendanceClosingStatus.WAITING_SUBMITTED for day in self.days)
        talent = PayrollTalentView(
            employee_id=_EMPLOYEE_ID,
            nrp="TEST1",
            name="Andi",
            role="Developer",
            status=(
                AttendanceClosingStatus.NEEDS_TALENT_ACTION
                if actionable
                else AttendanceClosingStatus.WAITING_SUBMITTED
            ),
            evaluated_days=len(self.days),
            complete_days=0,
            waiting_days=waiting,
            actionable_days=actionable,
            unverified_days=0,
            days=tuple(self.days),
        )
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=date(2026, 9, 18),
            summary=PayrollSummary(1, 0, waiting, actionable, 0),
            talents=(talent,),
        )


@pytest.mark.asyncio
async def test_pending_prior_same_gap_creates_progressive_suggestion() -> None:
    service = AttendanceReminderRoutingService(
        _Payroll(_prior_pending_clock_out(), _current_missing_clock_out())
    )

    result = await service.first_actionable(
        _context(),
        employee_id=_EMPLOYEE_ID,
        now=_NOW,
    )

    assert result.status is AttendanceReminderRouteStatus.OPEN
    assert result.selection is not None
    suggestion = result.selection.same_gap_suggestion
    assert suggestion is not None
    assert suggestion.source_work_date == date(2026, 9, 4)
    assert suggestion.resolution_type == "missing_clock_out"
    assert suggestion.proposed_check_out == time(17, 40)

    rendered = render_payroll_repeat_prompt(result.selection)
    assert "7 September" in rendered
    assert "4 September" in rendered
    assert "Clock Out 17:40" in rendered
    assert "jam pulangnya sama" in rendered
    assert PAYROLL_REPEAT_SAME_ACTION_ID in rendered
    assert PAYROLL_REPEAT_DIFFERENT_ACTION_ID in rendered


@pytest.mark.asyncio
async def test_non_pending_or_different_gap_does_not_offer_same_shortcut() -> None:
    approved = _prior_pending_clock_out(resolution_status="approved")
    approved_service = AttendanceReminderRoutingService(
        _Payroll(approved, _current_missing_clock_out())
    )
    approved_result = await approved_service.first_actionable(
        _context(), employee_id=_EMPLOYEE_ID, now=_NOW
    )
    assert approved_result.selection is not None
    assert approved_result.selection.same_gap_suggestion is None

    prior_clock_in = _day(
        key=_FIRST_KEY,
        work_date=date(2026, 9, 4),
        raw_in=None,
        raw_out="17:42",
        status=AttendanceClosingStatus.WAITING_SUBMITTED,
        reason=AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST,
        actionable=False,
        resolution_status="pending",
        resolution_type="missing_clock_in",
        proposed_in="07:30",
    )
    different_service = AttendanceReminderRoutingService(
        _Payroll(prior_clock_in, _current_missing_clock_out())
    )
    different_result = await different_service.first_actionable(
        _context(), employee_id=_EMPLOYEE_ID, now=_NOW
    )
    assert different_result.selection is not None
    assert different_result.selection.same_gap_suggestion is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sama", PayrollRepeatCommand.SAME),
        ("1", PayrollRepeatCommand.SAME),
        ("berbeda", PayrollRepeatCommand.DIFFERENT),
        ("beda", PayrollRepeatCommand.DIFFERENT),
        ("2", PayrollRepeatCommand.DIFFERENT),
    ],
)
def test_repeat_command_supports_button_text_and_numeric_fallback(
    text: str,
    expected: PayrollRepeatCommand,
) -> None:
    assert parse_payroll_repeat_command(text) is expected


class _State:
    def __init__(self, saved: AttendanceResolutionDraft | None) -> None:
        self.saved = saved
        self.saved_calls: list[tuple[time | None, time | None]] = []
        self.cleared = 0

    async def save_proposal(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: object | None = None,
    ) -> AttendanceResolutionDraft | None:
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        assert attendance_key == _NEXT_KEY
        assert resolution_type is ResolutionType.MISSING_CLOCK_OUT
        assert absence_type is None
        self.saved_calls.append((proposed_check_in, proposed_check_out))
        return self.saved

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared += 1


class _Router:
    def __init__(self, result: AttendanceReminderRouteResult) -> None:
        self.result = result

    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        assert context.employee_id == _EMPLOYEE_ID
        assert employee_id == _EMPLOYEE_ID
        assert now == _NOW
        return self.result


def _draft(*, proposed_out: time | None = None) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=_NEXT_KEY,
        employee_id=_EMPLOYEE_ID,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        work_date=date(2026, 9, 7),
        proposed_check_out=proposed_out,
        has_evidence=False,
    )


async def _repeat_selection() -> AttendanceReminderRouteResult:
    service = AttendanceReminderRoutingService(
        _Payroll(_prior_pending_clock_out(), _current_missing_clock_out())
    )
    return await service.first_actionable(
        _context(), employee_id=_EMPLOYEE_ID, now=_NOW
    )


@pytest.mark.asyncio
async def test_same_revalidates_then_copies_only_the_explicit_clock_to_current_draft() -> None:
    routed = await _repeat_selection()
    state = _State(_draft(proposed_out=time(17, 40)))

    response = await handle_payroll_repeat_command(
        command=PayrollRepeatCommand.SAME,
        jid=_JID,
        draft=_draft(),
        context=_context(),
        now=_NOW,
        state=state,
        routing=_Router(routed),
    )

    assert state.saved_calls == [(None, time(17, 40))]
    assert state.cleared == 0
    assert "jam yang sama dipakai" in response
    assert "Clock Out: 17:40" in response
    assert "kirim screenshot/bukti attendance" in response
    assert "diajukan ke PMO" not in response


@pytest.mark.asyncio
async def test_different_returns_normal_gap_prompt_without_copying_proposal() -> None:
    routed = await _repeat_selection()
    state = _State(_draft(proposed_out=time(17, 40)))

    response = await handle_payroll_repeat_command(
        command=PayrollRepeatCommand.DIFFERENT,
        jid=_JID,
        draft=_draft(),
        context=_context(),
        now=_NOW,
        state=state,
        routing=_Router(routed),
    )

    assert state.saved_calls == []
    assert state.cleared == 0
    assert "Jam pulang berapa?" in response
    assert "17:40" not in response


@pytest.mark.asyncio
async def test_same_falls_back_to_explicit_input_when_suggestion_disappears() -> None:
    no_suggestion_service = AttendanceReminderRoutingService(
        _Payroll(_current_missing_clock_out())
    )
    routed = await no_suggestion_service.first_actionable(
        AttendanceReminderContext.create(
            employee_id=_EMPLOYEE_ID,
            cycle_id=_CYCLE.cycle_id,
            attendance_keys=(_NEXT_KEY,),
            expires_at=_NOW + timedelta(days=2),
        ),
        employee_id=_EMPLOYEE_ID,
        now=_NOW,
    )
    state = _State(_draft(proposed_out=time(17, 40)))

    response = await handle_payroll_repeat_command(
        command=PayrollRepeatCommand.SAME,
        jid=_JID,
        draft=_draft(),
        context=AttendanceReminderContext.create(
            employee_id=_EMPLOYEE_ID,
            cycle_id=_CYCLE.cycle_id,
            attendance_keys=(_NEXT_KEY,),
            expires_at=_NOW + timedelta(days=2),
        ),
        now=_NOW,
        state=state,
        routing=_Router(routed),
    )

    assert state.saved_calls == []
    assert state.cleared == 0
    assert "Jam pulang berapa?" in response
