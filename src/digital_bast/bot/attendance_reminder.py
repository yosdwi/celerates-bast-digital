"""Compose concise Payroll attendance reminders from the closing projection.

P08 is deliberately side-effect free: it does not dispatch WhatsApp messages and
it does not mutate attendance. The draft carries the exact P07 reminder context
that must be persisted by the later dispatch orchestration before a message is
sent, so user-visible ordering is never reconstructed from a newer projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
)
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.interactive import InteractiveAction, InteractiveReply

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_read import PayrollDayView, PayrollTalentView

ATTENDANCE_REMINDER_START_ACTION_ID: Final = "payroll_attendance_start"
ATTENDANCE_REMINDER_LATER_ACTION_ID: Final = "payroll_attendance_later"
_MAX_VISIBLE_GAPS: Final = 5
_MONTH_LABELS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)
_REJECTED_ACTION_LABELS: Final = {
    "missing_clock_in": "Clock In perlu diperbaiki",
    "missing_clock_out": "Clock Out perlu diperbaiki",
    "missing_both_worked": "Clock In & Clock Out perlu diperbaiki",
    "absence": "Pengajuan ketidakhadiran perlu diperbaiki",
}


@dataclass(frozen=True, slots=True)
class AttendanceReminderDraft:
    """A reminder payload plus the immutable context that gives it meaning."""

    text: str
    actions: tuple[InteractiveAction, ...]
    context: AttendanceReminderContext

    def as_interactive(self) -> InteractiveReply:
        """Return the existing bot envelope for transports that support it."""
        return InteractiveReply(
            text=self.text,
            actions=self.actions,
            footer="Digital BAST · Payroll",
        )

    def as_plain_text(self) -> str:
        """Render the required numbered fallback for today's plain-text outbound."""
        lines = [self.text, ""]
        lines.extend(
            f"{index}. {action.label}"
            for index, action in enumerate(self.actions, 1)
        )
        lines.extend(("", 'Balas 1/2 atau tulis "lengkapi" / "nanti".'))
        return "\n".join(lines)


def _date_label(day: PayrollDayView) -> str:
    return f"{day.work_date.day} {_MONTH_LABELS[day.work_date.month - 1]}"


def _is_missing(value: str | None) -> bool:
    return value is None or not value.strip()


def _rejected_action(day: PayrollDayView) -> str:
    if day.resolution_type is None:
        return "Attendance perlu diperbaiki"
    return _REJECTED_ACTION_LABELS.get(
        day.resolution_type,
        "Attendance perlu diperbaiki",
    )


def _action_label(day: PayrollDayView) -> str:
    if day.reason is AttendanceClosingReason.CORRECTION_REJECTED:
        return _rejected_action(day)

    missing_in = _is_missing(day.raw_check_in)
    missing_out = _is_missing(day.raw_check_out)
    if missing_in and missing_out:
        return "Clock In & Clock Out belum ada"
    if missing_in:
        return "Clock In belum ada"
    if missing_out:
        return "Clock Out belum ada"
    return "Attendance perlu dilengkapi"


def _message_text(
    talent: PayrollTalentView,
    cycle: PayrollCycle,
    actionable: tuple[PayrollDayView, ...],
) -> str:
    intro = (
        f"Halo {talent.name}, ada {len(actionable)} attendance "
        f"{cycle.label} yang perlu dilengkapi:"
    )
    lines = [intro, ""]
    visible = actionable[:_MAX_VISIBLE_GAPS]
    lines.extend(f"{_date_label(day)} — {_action_label(day)}" for day in visible)
    hidden_count = len(actionable) - len(visible)
    if hidden_count > 0:
        lines.append(f"+{hidden_count} attendance lainnya")
    return "\n".join(lines)


def compose_attendance_reminder(
    talent: PayrollTalentView,
    cycle: PayrollCycle,
    *,
    expires_at: datetime,
    context_id: UUID | None = None,
) -> AttendanceReminderDraft | None:
    """Build a current-action reminder without dispatching it.

    Only rows explicitly marked ``talent_action_required`` enter the message or
    context. If any such row lacks a canonical attendance key, composition fails
    closed and returns ``None`` rather than sending a reminder that cannot later
    resolve safely.
    """
    if talent.status is not AttendanceClosingStatus.NEEDS_TALENT_ACTION:
        return None

    actionable = tuple(
        sorted(
            (day for day in talent.days if day.talent_action_required),
            key=lambda day: (day.work_date, day.attendance_key or ""),
        )
    )
    if not actionable:
        return None

    attendance_keys = tuple(day.attendance_key or "" for day in actionable)
    if any(not key.strip() for key in attendance_keys):
        return None

    try:
        context = AttendanceReminderContext.create(
            employee_id=talent.employee_id,
            cycle_id=cycle.cycle_id,
            attendance_keys=attendance_keys,
            expires_at=expires_at,
            context_id=context_id,
        )
    except ValueError:
        return None

    actions = (
        InteractiveAction(ATTENDANCE_REMINDER_START_ACTION_ID, "Lengkapi"),
        InteractiveAction(ATTENDANCE_REMINDER_LATER_ACTION_ID, "Nanti"),
    )
    return AttendanceReminderDraft(
        text=_message_text(talent, cycle, actionable),
        actions=actions,
        context=context,
    )
