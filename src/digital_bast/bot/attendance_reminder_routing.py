"""Resolve a reminder action against its stable Payroll attendance snapshot.

P09 selects and renders the next current actionable gap. P14 extends that
selection with an optional progressive same-gap suggestion derived from a prior
WAITING_SUBMITTED item in the same stable P07 snapshot. The suggestion is never
persisted as a new proposal until the Talent explicitly chooses ``Sama``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

from digital_bast.application.attendance_closing import AttendanceClosingReason
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.bot.attendance_reminder import (
    ATTENDANCE_REMINDER_LATER_ACTION_ID,
    ATTENDANCE_REMINDER_START_ACTION_ID,
)
from digital_bast.domain.completion import format_day

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_read import PayrollDayView, PayrollOverview
    from digital_bast.bot.attendance_context import AttendanceReminderContext


class AttendanceReminderCommand(StrEnum):
    START = "start"
    LATER = "later"


class AttendanceReminderRouteStatus(StrEnum):
    OPEN = "open"
    NO_ACTION = "no_action"
    INVALID_CONTEXT = "invalid_context"
    NOT_OWNED = "not_owned"


@dataclass(frozen=True, slots=True)
class AttendanceSameGapSuggestion:
    source_work_date: date
    resolution_type: str
    proposed_check_in: time | None = None
    proposed_check_out: time | None = None


@dataclass(frozen=True, slots=True)
class AttendanceReminderGapSelection:
    cycle: PayrollCycle
    day: PayrollDayView
    remaining_actionable: int
    same_gap_suggestion: AttendanceSameGapSuggestion | None = None


@dataclass(frozen=True, slots=True)
class AttendanceReminderRouteResult:
    status: AttendanceReminderRouteStatus
    selection: AttendanceReminderGapSelection | None = None


class PayrollOverviewReader(Protocol):
    async def overview(self, cycle: PayrollCycle, *, now: datetime) -> PayrollOverview: ...


_START_WORDS: Final = frozenset(
    {
        ATTENDANCE_REMINDER_START_ACTION_ID,
        "lengkapi",
        "lengkapi sekarang",
        "lanjut",
    }
)
_LATER_WORDS: Final = frozenset(
    {
        ATTENDANCE_REMINDER_LATER_ACTION_ID,
        "nanti",
        "nanti dulu",
        "selesai",
        "selesai dulu",
    }
)
_SINGLE_GAP_TYPES: Final = frozenset({"missing_clock_in", "missing_clock_out"})


def parse_attendance_reminder_command(
    text: str,
    *,
    allow_digit_shortcuts: bool,
) -> AttendanceReminderCommand | None:
    """Parse only explicit reminder actions; natural correction text is P10/P36."""
    normalized = text.strip().casefold()
    if normalized in _START_WORDS or (allow_digit_shortcuts and normalized == "1"):
        return AttendanceReminderCommand.START
    if normalized in _LATER_WORDS or (allow_digit_shortcuts and normalized == "2"):
        return AttendanceReminderCommand.LATER
    return None


def _cycle_from_id(cycle_id: str) -> PayrollCycle | None:
    parts = cycle_id.split(":")
    if len(parts) != 3:
        return None
    try:
        label_year_text, label_month_text = parts[0].split("-", 1)
        label_year = int(label_year_text)
        label_month = int(label_month_text)
        start = date.fromisoformat(parts[1])
        end = date.fromisoformat(parts[2])
        candidate = payroll_cycle(label_year, label_month, end.day)
    except ValueError:
        return None
    if candidate.period.start != start or candidate.period.end != end:
        return None
    if candidate.cycle_id != cycle_id:
        return None
    return candidate


def _is_missing(value: str | None) -> bool:
    return value is None or not value.strip()


def _single_gap_type(day: PayrollDayView) -> str | None:
    missing_in = _is_missing(day.raw_check_in)
    missing_out = _is_missing(day.raw_check_out)
    if missing_in and not missing_out:
        return "missing_clock_in"
    if missing_out and not missing_in:
        return "missing_clock_out"
    return None


def _clock(value: str | None) -> time | None:
    if value is None or not value.strip():
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None


def _same_gap_suggestion(
    *,
    context: AttendanceReminderContext,
    by_key: dict[str, PayrollDayView],
    current_position: int,
    current_day: PayrollDayView,
) -> AttendanceSameGapSuggestion | None:
    current_type = _single_gap_type(current_day)
    if current_type not in _SINGLE_GAP_TYPES:
        return None

    for prior_key in reversed(context.attendance_keys[:current_position]):
        prior = by_key.get(prior_key)
        if prior is None:
            continue
        if prior.resolution_status != "pending" or prior.resolution_type != current_type:
            continue
        proposed_in = _clock(prior.proposed_check_in)
        proposed_out = _clock(prior.proposed_check_out)
        if current_type == "missing_clock_in" and proposed_in is None:
            continue
        if current_type == "missing_clock_out" and proposed_out is None:
            continue
        return AttendanceSameGapSuggestion(
            source_work_date=prior.work_date,
            resolution_type=current_type,
            proposed_check_in=proposed_in,
            proposed_check_out=proposed_out,
        )
    return None


class AttendanceReminderRoutingService:
    def __init__(self, payroll: PayrollOverviewReader) -> None:
        self._payroll = payroll

    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        if context.employee_id != employee_id:
            return AttendanceReminderRouteResult(AttendanceReminderRouteStatus.NOT_OWNED)

        cycle = _cycle_from_id(context.cycle_id)
        if cycle is None:
            return AttendanceReminderRouteResult(
                AttendanceReminderRouteStatus.INVALID_CONTEXT
            )

        overview = await self._payroll.overview(cycle, now=now)
        talent = next(
            (item for item in overview.talents if item.employee_id == employee_id),
            None,
        )
        if talent is None:
            return AttendanceReminderRouteResult(
                AttendanceReminderRouteStatus.INVALID_CONTEXT
            )

        by_key = {
            day.attendance_key: day
            for day in talent.days
            if day.attendance_key is not None
        }
        current_actionable = {
            key for key, day in by_key.items() if day.talent_action_required
        }
        for position, key in enumerate(context.attendance_keys):
            day = by_key.get(key)
            if day is None or not day.talent_action_required:
                continue
            remaining = sum(
                snapshot_key in current_actionable
                for snapshot_key in context.attendance_keys
            )
            return AttendanceReminderRouteResult(
                AttendanceReminderRouteStatus.OPEN,
                AttendanceReminderGapSelection(
                    cycle,
                    day,
                    remaining,
                    _same_gap_suggestion(
                        context=context,
                        by_key=by_key,
                        current_position=position,
                        current_day=day,
                    ),
                ),
            )
        return AttendanceReminderRouteResult(AttendanceReminderRouteStatus.NO_ACTION)


def render_attendance_gap_prompt(selection: AttendanceReminderGapSelection) -> str:
    """Ask only the next missing attendance fact; no Mobile/menu redirect."""
    day = selection.day
    label = format_day(day.work_date)
    missing_in = _is_missing(day.raw_check_in)
    missing_out = _is_missing(day.raw_check_out)
    rejected = day.reason is AttendanceClosingReason.CORRECTION_REJECTED

    lines = [label]
    if missing_in and missing_out:
        if rejected and day.resolution_type == "absence":
            lines.extend(
                (
                    "Pengajuan ketidakhadiran perlu diperbaiki.",
                    "",
                    "Hari itu kamu bekerja atau tidak masuk?",
                )
            )
        else:
            lines.extend(
                (
                    "Clock In dan Clock Out belum ada.",
                    "",
                    "Kirim jam masuk dan jam pulang, contoh: 07:30 17:00.",
                )
            )
    elif missing_in:
        if day.raw_check_out:
            lines.append(f"Clock Out tercatat {day.raw_check_out}.")
        lines.append("Clock In perlu dikoreksi." if rejected else "Clock In belum ada.")
        question = "Jam masuk yang benar berapa?" if rejected else "Jam masuk berapa?"
        lines.extend(("", question))
    elif missing_out:
        if day.raw_check_in:
            lines.append(f"Clock In tercatat {day.raw_check_in}.")
        lines.append("Clock Out perlu dikoreksi." if rejected else "Clock Out belum ada.")
        question = "Jam pulang yang benar berapa?" if rejected else "Jam pulang berapa?"
        lines.extend(("", question))
    else:
        lines.extend(("Attendance ini perlu diperbaiki.", "", "Informasi yang benar apa?"))

    if selection.remaining_actionable > 1:
        remaining = selection.remaining_actionable - 1
        lines.extend(("", f"Masih ada {remaining} tanggal setelah ini."))
    return "\n".join(lines)
