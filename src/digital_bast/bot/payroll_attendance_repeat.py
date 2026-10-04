"""Progressive same-gap shortcut for Payroll attendance correction.

P14 never bulk-applies a correction. A ``Sama`` suggestion is derived from a
previous WAITING_SUBMITTED item in the same stable reminder snapshot and is
revalidated again when the Talent responds. Only then is the proposed clock
copied into the current durable draft; evidence and explicit submit remain
per-attendance steps.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderRouteStatus,
    render_attendance_gap_prompt,
)
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.interactive import interactive
from digital_bast.bot.payroll_attendance_draft import render_payroll_draft_prompt
from digital_bast.domain.completion import format_day

if TYPE_CHECKING:
    from datetime import datetime, time

    from digital_bast.bot.attendance_context import AttendanceReminderContext
    from digital_bast.bot.attendance_reminder_routing import (
        AttendanceReminderGapSelection,
        AttendanceReminderRouteResult,
    )
    from digital_bast.bot.attendance_resolution import AbsenceType
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft


PAYROLL_REPEAT_SAME_ACTION_ID: Final = "payroll_attendance_same"
PAYROLL_REPEAT_DIFFERENT_ACTION_ID: Final = "payroll_attendance_different"


class PayrollRepeatCommand(StrEnum):
    SAME = "same"
    DIFFERENT = "different"


_SAME_WORDS: Final = frozenset({PAYROLL_REPEAT_SAME_ACTION_ID, "sama", "1"})
_DIFFERENT_WORDS: Final = frozenset(
    {PAYROLL_REPEAT_DIFFERENT_ACTION_ID, "berbeda", "beda", "2"}
)


def parse_payroll_repeat_command(text: str) -> PayrollRepeatCommand | None:
    normalized = text.strip().casefold()
    if normalized in _SAME_WORDS:
        return PayrollRepeatCommand.SAME
    if normalized in _DIFFERENT_WORDS:
        return PayrollRepeatCommand.DIFFERENT
    return None


def _clock_label(value: time | None) -> str:
    return value.strftime("%H:%M") if value is not None else "—"


def render_payroll_repeat_prompt(selection: AttendanceReminderGapSelection) -> str:
    suggestion = selection.same_gap_suggestion
    if suggestion is None:
        return render_attendance_gap_prompt(selection)

    day = selection.day
    lines = [format_day(day.work_date)]
    if suggestion.resolution_type == ResolutionType.MISSING_CLOCK_IN.value:
        if day.raw_check_out:
            lines.append(f"Clock Out tercatat {day.raw_check_out}.")
        lines.extend(
            (
                "Clock In belum ada.",
                "",
                f"{format_day(suggestion.source_work_date)} kamu mengajukan "
                f"Clock In {_clock_label(suggestion.proposed_check_in)}.",
                "Untuk tanggal ini jam masuknya sama?",
            )
        )
    else:
        if day.raw_check_in:
            lines.append(f"Clock In tercatat {day.raw_check_in}.")
        lines.extend(
            (
                "Clock Out belum ada.",
                "",
                f"{format_day(suggestion.source_work_date)} kamu mengajukan "
                f"Clock Out {_clock_label(suggestion.proposed_check_out)}.",
                "Untuk tanggal ini jam pulangnya sama?",
            )
        )

    return interactive(
        "\n".join(lines),
        (PAYROLL_REPEAT_SAME_ACTION_ID, "Sama"),
        (PAYROLL_REPEAT_DIFFERENT_ACTION_ID, "Berbeda"),
        footer="Payroll Attendance",
    )


class AttendanceRepeatState(Protocol):
    async def save_proposal(  # noqa: PLR0913
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: AbsenceType | None = None,
    ) -> AttendanceResolutionDraft | None: ...

    async def clear(self, wa_jid: str) -> None: ...


class AttendanceRepeatRouter(Protocol):
    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult: ...


async def handle_payroll_repeat_command(  # noqa: PLR0913
    *,
    command: PayrollRepeatCommand,
    jid: str,
    draft: AttendanceResolutionDraft,
    context: AttendanceReminderContext,
    now: datetime,
    state: AttendanceRepeatState,
    routing: AttendanceRepeatRouter,
) -> str:
    """Revalidate and handle one ``Sama/Berbeda`` response without bulk mutation."""
    routed = await routing.first_actionable(
        context,
        employee_id=draft.employee_id,
        now=now,
    )
    if (
        routed.status is not AttendanceReminderRouteStatus.OPEN
        or routed.selection is None
        or routed.selection.day.attendance_key != draft.attendance_key
    ):
        await state.clear(jid)
        return (
            "Data attendance berubah sejak pertanyaan terakhir. "
            "Balas `lengkapi` lagi untuk memuat kondisi terbaru."
        )

    if command is PayrollRepeatCommand.DIFFERENT:
        return render_attendance_gap_prompt(routed.selection)

    suggestion = routed.selection.same_gap_suggestion
    if suggestion is None or suggestion.resolution_type != draft.resolution_type.value:
        return render_attendance_gap_prompt(routed.selection)

    saved = await state.save_proposal(
        jid,
        draft.employee_id,
        draft.attendance_key,
        draft.resolution_type,
        proposed_check_in=suggestion.proposed_check_in,
        proposed_check_out=suggestion.proposed_check_out,
        absence_type=None,
    )
    if saved is None:
        await state.clear(jid)
        return (
            "Data attendance berubah sebelum jam yang sama bisa dipakai. "
            "Balas `lengkapi` lagi untuk memuat kondisi terbaru."
        )
    return render_payroll_draft_prompt(
        saved,
        prefix="Oke, jam yang sama dipakai untuk tanggal ini.",
    )
