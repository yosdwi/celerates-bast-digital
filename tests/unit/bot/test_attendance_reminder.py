from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_read import PayrollDayView, PayrollTalentView
from digital_bast.bot.attendance_reminder import compose_attendance_reminder

_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_EXPIRES_AT = _NOW + timedelta(days=2)
_CONTEXT_ID = UUID("00000000-0000-0000-0000-000000000008")


def _day(
    day: int,
    *,
    key: str | None = None,
    raw_in: str | None = "07:32",
    raw_out: str | None = None,
    status: AttendanceClosingStatus = AttendanceClosingStatus.NEEDS_TALENT_ACTION,
    reason: AttendanceClosingReason = AttendanceClosingReason.GAP_UNCOVERED,
    talent_action_required: bool = True,
    resolution_type: str | None = None,
    rejection_reason: str | None = None,
) -> PayrollDayView:
    return PayrollDayView(
        attendance_id=day,
        attendance_key=key if key is not None else f"attendance:{day}",
        work_date=date(2026, 9, day),
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in=raw_in,
        raw_check_out=raw_out,
        proposed_check_in=None,
        proposed_check_out=None,
        resolution_id=None,
        resolution_status=None,
        resolution_type=resolution_type,
        absence_type=None,
        rejection_reason=rejection_reason,
        has_evidence=False,
        status=status,
        reason=reason,
        talent_action_required=talent_action_required,
    )


def _talent(
    *days: PayrollDayView,
    status: AttendanceClosingStatus = AttendanceClosingStatus.NEEDS_TALENT_ACTION,
) -> PayrollTalentView:
    actionable = sum(day.talent_action_required for day in days)
    waiting = sum(day.status is AttendanceClosingStatus.WAITING_SUBMITTED for day in days)
    complete = sum(day.status is AttendanceClosingStatus.COMPLETE for day in days)
    return PayrollTalentView(
        employee_id="employee-1",
        nrp="12345",
        name="Andi",
        role="Developer",
        status=status,
        evaluated_days=len(days),
        complete_days=complete,
        waiting_days=waiting,
        actionable_days=actionable,
        unverified_days=0,
        days=days,
    )


def test_composer_keeps_only_current_action_and_builds_p07_snapshot() -> None:
    cycle = payroll_cycle(2026, 9)
    talent = _talent(
        _day(7, key="attendance:seven", raw_in=None, raw_out="17:51"),
        _day(4, key="attendance:four"),
        _day(
            8,
            status=AttendanceClosingStatus.WAITING_SUBMITTED,
            reason=AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST,
            talent_action_required=False,
        ),
        _day(
            9,
            raw_out="17:40",
            status=AttendanceClosingStatus.COMPLETE,
            reason=AttendanceClosingReason.RAW_COMPLETE,
            talent_action_required=False,
        ),
    )

    draft = compose_attendance_reminder(
        talent,
        cycle,
        expires_at=_EXPIRES_AT,
        context_id=_CONTEXT_ID,
    )

    assert draft is not None
    assert "ada 2 attendance Payroll September 2026" in draft.text
    assert draft.text.index("4 Sep") < draft.text.index("7 Sep")
    assert "4 Sep — Clock Out belum ada" in draft.text
    assert "7 Sep — Clock In belum ada" in draft.text
    assert "8 Sep" not in draft.text
    assert "9 Sep" not in draft.text
    assert draft.context.context_id == _CONTEXT_ID
    assert draft.context.employee_id == "employee-1"
    assert draft.context.cycle_id == cycle.cycle_id
    assert draft.context.attendance_keys == ("attendance:four", "attendance:seven")


def test_composer_exposes_only_lengkapi_and_nanti_with_plain_text_fallback() -> None:
    draft = compose_attendance_reminder(
        _talent(_day(4)),
        payroll_cycle(2026, 9),
        expires_at=_EXPIRES_AT,
        context_id=_CONTEXT_ID,
    )

    assert draft is not None
    assert tuple(action.label for action in draft.actions) == ("Lengkapi", "Nanti")
    assert tuple(action.id for action in draft.actions) == (
        "payroll_attendance_start",
        "payroll_attendance_later",
    )
    assert draft.as_interactive().digit_shortcuts is True
    plain = draft.as_plain_text()
    assert "1. Lengkapi" in plain
    assert "2. Nanti" in plain
    assert 'Balas 1/2 atau tulis "lengkapi" / "nanti".' in plain


def test_composer_skips_waiting_complete_and_unverified_only_talents() -> None:
    cycle = payroll_cycle(2026, 9)
    waiting = _talent(
        _day(
            4,
            status=AttendanceClosingStatus.WAITING_SUBMITTED,
            reason=AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST,
            talent_action_required=False,
        ),
        status=AttendanceClosingStatus.WAITING_SUBMITTED,
    )
    complete = _talent(
        _day(
            4,
            raw_out="17:40",
            status=AttendanceClosingStatus.COMPLETE,
            reason=AttendanceClosingReason.RAW_COMPLETE,
            talent_action_required=False,
        ),
        status=AttendanceClosingStatus.COMPLETE,
    )
    unverified = _talent(
        PayrollDayView(
            attendance_id=None,
            attendance_key=None,
            work_date=date(2026, 9, 4),
            schedule_state=AttendanceScheduleState.WORKING,
            source_state=AttendanceSourceState.UNAVAILABLE,
            raw_check_in=None,
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
            reason=AttendanceClosingReason.SOURCE_UNAVAILABLE,
            talent_action_required=False,
        )
    )

    assert compose_attendance_reminder(waiting, cycle, expires_at=_EXPIRES_AT) is None
    assert compose_attendance_reminder(complete, cycle, expires_at=_EXPIRES_AT) is None
    assert compose_attendance_reminder(unverified, cycle, expires_at=_EXPIRES_AT) is None


def test_composer_fails_closed_for_unaddressable_or_duplicate_actionable_rows() -> None:
    cycle = payroll_cycle(2026, 9)

    assert (
        compose_attendance_reminder(
            _talent(_day(4, key="")),
            cycle,
            expires_at=_EXPIRES_AT,
        )
        is None
    )
    assert (
        compose_attendance_reminder(
            _talent(_day(4, key="attendance:same"), _day(7, key="attendance:same")),
            cycle,
            expires_at=_EXPIRES_AT,
        )
        is None
    )


def test_rejected_request_is_worded_as_current_correction_action() -> None:
    draft = compose_attendance_reminder(
        _talent(
            _day(
                4,
                reason=AttendanceClosingReason.CORRECTION_REJECTED,
                resolution_type="missing_clock_out",
                rejection_reason="Jam pulang tidak sesuai bukti",
            )
        ),
        payroll_cycle(2026, 9),
        expires_at=_EXPIRES_AT,
    )

    assert draft is not None
    assert "4 Sep — Clock Out perlu diperbaiki" in draft.text
    assert "belum ada" not in draft.text


def test_large_reminder_stays_concise_but_snapshot_keeps_every_actionable_key() -> None:
    days = tuple(_day(day) for day in (4, 5, 6, 7, 8, 9))

    draft = compose_attendance_reminder(
        _talent(*days),
        payroll_cycle(2026, 9),
        expires_at=_EXPIRES_AT,
    )

    assert draft is not None
    assert "4 Sep" in draft.text
    assert "8 Sep" in draft.text
    assert "9 Sep" not in draft.text
    assert "+1 attendance lainnya" in draft.text
    assert draft.context.attendance_keys == tuple(
        f"attendance:{day}" for day in (4, 5, 6, 7, 8, 9)
    )
