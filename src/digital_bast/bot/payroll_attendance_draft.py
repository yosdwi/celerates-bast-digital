"""Pure helpers for the Payroll attendance correction draft flow.

A Payroll draft is filled time-first, then evidence is attached to that exact
attendance identity. Only when both proposal and evidence are present does the
Talent get an explicit review step. Nothing in this module submits a PMO request.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm import proposals
from digital_bast.bot.interactive import interactive
from digital_bast.domain.completion import format_day

if TYPE_CHECKING:
    from digital_bast.bot.attendance_resolution_dm import ResolutionProposal
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft


PAYROLL_DRAFT_SUBMIT_ACTION_ID: Final = "payroll_attendance_submit"
PAYROLL_DRAFT_EDIT_ACTION_ID: Final = "payroll_attendance_edit"


class PayrollDraftCommand(StrEnum):
    SUBMIT = "submit"
    EDIT = "edit"


_SUBMIT_WORDS: Final = frozenset(
    {
        PAYROLL_DRAFT_SUBMIT_ACTION_ID,
        "ajukan",
        "submit",
        "1",
    }
)
_EDIT_WORDS: Final = frozenset(
    {
        PAYROLL_DRAFT_EDIT_ACTION_ID,
        "ubah",
        "edit",
        "2",
    }
)


def parse_payroll_draft_command(text: str) -> PayrollDraftCommand | None:
    normalized = text.strip().casefold()
    if normalized in _SUBMIT_WORDS:
        return PayrollDraftCommand.SUBMIT
    if normalized in _EDIT_WORDS:
        return PayrollDraftCommand.EDIT
    return None


def select_payroll_proposal(
    draft: AttendanceResolutionDraft,
    text: str,
) -> ResolutionProposal | None:
    """Pick only a proposal that can satisfy the currently selected source gap."""
    parsed = proposals(text)
    if draft.resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return next(
            (
                item
                for item in parsed
                if item.resolution_type
                in {ResolutionType.MISSING_BOTH_WORKED, ResolutionType.ABSENCE}
            ),
            None,
        )
    return next(
        (item for item in parsed if item.resolution_type is draft.resolution_type),
        None,
    )


def _draft_value_lines(draft: AttendanceResolutionDraft) -> tuple[str, ...]:
    if draft.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        value = draft.proposed_check_in
        return (f"Clock In: {value.strftime('%H:%M')}" if value else "Clock In: —",)
    if draft.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        value = draft.proposed_check_out
        return (f"Clock Out: {value.strftime('%H:%M')}" if value else "Clock Out: —",)
    if draft.resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        check_in = draft.proposed_check_in
        check_out = draft.proposed_check_out
        return (
            f"Clock In: {check_in.strftime('%H:%M') if check_in else '—'}",
            f"Clock Out: {check_out.strftime('%H:%M') if check_out else '—'}",
        )
    absence = draft.absence_type.value.capitalize() if draft.absence_type is not None else "—"
    return (f"Status: {absence}",)


def _review_prompt(lines: list[str]) -> str:
    lines.extend(("Bukti: ✓", "", "Ajukan informasi ini?"))
    return interactive(
        "\n".join(lines),
        (PAYROLL_DRAFT_SUBMIT_ACTION_ID, "Ajukan"),
        (PAYROLL_DRAFT_EDIT_ACTION_ID, "Ubah"),
        footer="Payroll Attendance",
    )


def render_payroll_draft_prompt(
    draft: AttendanceResolutionDraft,
    *,
    prefix: str = "",
) -> str:
    """Render only the next explicit step; never imply submission before it happens."""
    date_label = format_day(draft.work_date) if draft.work_date is not None else "Attendance ini"
    lines: list[str] = []
    if prefix.strip():
        lines.extend((prefix.strip(), ""))

    if draft.has_proposal:
        lines.append(date_label)
        lines.extend(_draft_value_lines(draft))
        if draft.has_evidence:
            return _review_prompt(lines)
        lines.extend(
            (
                "",
                f"Sekarang kirim screenshot/bukti attendance untuk {date_label}.",
            )
        )
        return "\n".join(lines)

    lines.append(date_label)
    if draft.has_evidence:
        lines.extend(("Bukti sudah ada.", ""))

    if draft.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        lines.append("Jam masuk berapa?")
    elif draft.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        lines.append("Jam pulang berapa?")
    else:
        lines.extend(
            (
                "Kirim jam masuk dan jam pulang, contoh: 07:30 17:00.",
                "Kalau tidak masuk, kirim Cuti, Izin, atau Sakit.",
            )
        )
    return "\n".join(lines)
