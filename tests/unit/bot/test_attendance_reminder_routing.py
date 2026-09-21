from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

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
    AttendanceReminderCommand,
    AttendanceReminderRouteStatus,
    AttendanceReminderRoutingService,
    parse_attendance_reminder_command,
    render_attendance_gap_prompt,
)

_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_CYCLE = payroll_cycle(2026, 9)


def _day(
    day: int,
    key: str,
    *,
    raw_in: str | None = "07:32",
    raw_out: str | None = None,
    actionable: bool = True,
    reason: AttendanceClosingReason = AttendanceClosingReason.GAP_UNCOVERED,
    resolution_type: str | None = None,
) -> PayrollDayView:
    return PayrollDayView(
        attendance_id=day,
        attendance_key=key,
        work_date=date(2026, 9, day),
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in=raw_in,
        raw_check_out=raw_out,
        proposed_check_in=None,
        proposed_check_out=None,
        resolution_id=None,
        resolution_status="rejected" if reason is AttendanceClosingReason.CORRECTION_REJECTED else None,
        resolution_type=resolution_type,
        absence_type=None,
        rejection_reason=None,
        has_evidence=False,
        status=(
            AttendanceClosingStatus.NEEDS_TALENT_ACTION
            if actionable
            else AttendanceClosingStatus.COMPLETE
        ),
        reason=reason,
        talent_action_required=actionable,
    )


def _talent(*days: PayrollDayView) -> PayrollTalentView:
    actionable = sum(day.talent_action_required for day in days)
    return PayrollTalentView(
        employee_id="employee-1",
        nrp="12345",
        name="Andi",
        role="Developer",
        status=(
            AttendanceClosingStatus.NEEDS_TALENT_ACTION
            if actionable
            else AttendanceClosingStatus.COMPLETE
        ),
        evaluated_days=len(days),
        complete_days=len(days) - actionable,
        waiting_days=0,
        actionable_days=actionable,
        unverified_days=0,
        days=days,
    )


class _Payroll:
    def __init__(self, talent: PayrollTalentView) -> None:
        self.talent = talent
        self.calls: list[object] = []

    async def overview(self, cycle: object, *, now: datetime) -> PayrollOverview:
        self.calls.append((cycle, now))
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=date(2026, 9, 18),
            summary=PayrollSummary(1, 0, 0, 1, 0),
            talents=(self.talent,),
        )


def _context(*keys: str, employee_id: str = "employee-1") -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        employee_id,
        _CYCLE.cycle_id,
        keys,
        _NOW + timedelta(days=2),
    )


def test_command_parser_supports_ids_words_and_guarded_digits() -> None:
    assert (
        parse_attendance_reminder_command(
            "payroll_attendance_start", allow_digit_shortcuts=False
        )
        is AttendanceReminderCommand.START
    )
    assert (
        parse_attendance_reminder_command("lengkapi", allow_digit_shortcuts=False)
        is AttendanceReminderCommand.START
    )
    assert (
        parse_attendance_reminder_command("lanjut", allow_digit_shortcuts=False)
        is AttendanceReminderCommand.START
    )
    assert (
        parse_attendance_reminder_command("nanti", allow_digit_shortcuts=False)
        is AttendanceReminderCommand.LATER
    )
    assert (
        parse_attendance_reminder_command("selesai dulu", allow_digit_shortcuts=False)
        is AttendanceReminderCommand.LATER
    )
    assert parse_attendance_reminder_command("1", allow_digit_shortcuts=False) is None
    assert (
        parse_attendance_reminder_command("1", allow_digit_shortcuts=True)
        is AttendanceReminderCommand.START
    )
    assert (
        parse_attendance_reminder_command("2", allow_digit_shortcuts=True)
        is AttendanceReminderCommand.LATER
    )


@pytest.mark.asyncio
async def test_routing_keeps_snapshot_order_not_projection_order() -> None:
    payroll = _Payroll(
        _talent(
            _day(7, "attendance:seven", raw_in=None, raw_out="17:51"),
            _day(4, "attendance:four"),
        )
    )
    service = AttendanceReminderRoutingService(payroll)

    result = await service.first_actionable(
        _context("attendance:four", "attendance:seven"),
        employee_id="employee-1",
        now=_NOW,
    )

    assert result.status is AttendanceReminderRouteStatus.OPEN
    assert result.selection is not None
    assert result.selection.day.attendance_key == "attendance:four"
    assert result.selection.remaining_actionable == 2


@pytest.mark.asyncio
async def test_exact_date_can_select_second_gap_while_first_stays_actionable() -> None:
    service = AttendanceReminderRoutingService(
        _Payroll(
            _talent(
                _day(4, "attendance:four"),
                _day(7, "attendance:seven", raw_in=None, raw_out="17:51"),
            )
        )
    )

    result = await service.actionable_on(
        _context("attendance:four", "attendance:seven"),
        employee_id="employee-1",
        work_date=date(2026, 9, 7),
        now=_NOW,
    )

    assert result.status is AttendanceReminderRouteStatus.OPEN
    assert result.selection is not None
    assert result.selection.day.attendance_key == "attendance:seven"
    assert result.selection.remaining_actionable == 2


@pytest.mark.asyncio
async def test_exact_date_never_expands_beyond_reminder_snapshot() -> None:
    service = AttendanceReminderRoutingService(
        _Payroll(
            _talent(
                _day(4, "attendance:four"),
                _day(7, "attendance:seven"),
            )
        )
    )

    result = await service.actionable_on(
        _context("attendance:four"),
        employee_id="employee-1",
        work_date=date(2026, 9, 7),
        now=_NOW,
    )

    assert result.status is AttendanceReminderRouteStatus.NO_ACTION
    assert result.selection is None


@pytest.mark.asyncio
async def test_routing_skips_snapshot_item_that_is_no_longer_actionable() -> None:
    payroll = _Payroll(
        _talent(
            _day(
                4,
                "attendance:four",
                raw_out="17:40",
                actionable=False,
                reason=AttendanceClosingReason.RAW_COMPLETE,
            ),
            _day(7, "attendance:seven", raw_in=None, raw_out="17:51"),
        )
    )
    service = AttendanceReminderRoutingService(payroll)

    result = await service.first_actionable(
        _context("attendance:four", "attendance:seven"),
        employee_id="employee-1",
        now=_NOW,
    )

    assert result.status is AttendanceReminderRouteStatus.OPEN
    assert result.selection is not None
    assert result.selection.day.attendance_key == "attendance:seven"
    assert "Clock Out tercatat 17:51" in render_attendance_gap_prompt(result.selection)
    assert "Jam masuk berapa?" in render_attendance_gap_prompt(result.selection)


@pytest.mark.asyncio
async def test_routing_fails_closed_for_wrong_owner_or_cycle() -> None:
    service = AttendanceReminderRoutingService(_Payroll(_talent(_day(4, "attendance:four"))))

    wrong_owner = await service.first_actionable(
        _context("attendance:four", employee_id="other"),
        employee_id="employee-1",
        now=_NOW,
    )
    bad_cycle = AttendanceReminderContext.create(
        "employee-1",
        "not-a-cycle",
        ("attendance:four",),
        _NOW + timedelta(days=1),
    )
    invalid = await service.first_actionable(
        bad_cycle,
        employee_id="employee-1",
        now=_NOW,
    )

    assert wrong_owner.status is AttendanceReminderRouteStatus.NOT_OWNED
    assert invalid.status is AttendanceReminderRouteStatus.INVALID_CONTEXT


@pytest.mark.asyncio
async def test_routing_returns_no_action_when_snapshot_is_already_resolved() -> None:
    service = AttendanceReminderRoutingService(
        _Payroll(
            _talent(
                _day(
                    4,
                    "attendance:four",
                    raw_out="17:40",
                    actionable=False,
                    reason=AttendanceClosingReason.RAW_COMPLETE,
                )
            )
        )
    )

    result = await service.first_actionable(
        _context("attendance:four"),
        employee_id="employee-1",
        now=_NOW,
    )

    assert result.status is AttendanceReminderRouteStatus.NO_ACTION


def test_missing_both_prompt_is_button_first_and_keeps_remaining_count() -> None:
    selection = type("Selection", (), {})()
    selection.cycle = _CYCLE
    selection.day = _day(4, "attendance:four", raw_in=None, raw_out=None)
    selection.remaining_actionable = 2

    payload = json.loads(render_attendance_gap_prompt(selection))

    assert payload["kind"] == "interactive"
    assert "Hari itu kamu masuk kerja atau tidak masuk?" in payload["text"]
    assert "Masih ada 1 tanggal setelah ini" in payload["text"]
    assert [action["label"] for action in payload["actions"]] == [
        "Masuk kerja",
        "Tidak masuk",
    ]
    assert [action["id"] for action in payload["actions"]] == [
        "payroll_attendance_worked",
        "payroll_attendance_absent",
    ]


def test_prompt_for_rejected_clock_out_is_correction_specific_and_not_mobile() -> None:
    selection = type("Selection", (), {})()
    selection.cycle = _CYCLE
    selection.day = _day(
        4,
        "attendance:four",
        reason=AttendanceClosingReason.CORRECTION_REJECTED,
        resolution_type="missing_clock_out",
    )
    selection.remaining_actionable = 1

    prompt = render_attendance_gap_prompt(selection)

    assert "Clock In tercatat 07:32" in prompt
    assert "Clock Out perlu dikoreksi" in prompt
    assert "Jam pulang yang benar berapa?" in prompt
    assert "Mobile" not in prompt
    assert "menu" not in prompt.casefold()
