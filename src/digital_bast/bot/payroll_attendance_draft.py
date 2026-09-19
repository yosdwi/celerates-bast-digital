"""Pure helpers for the Payroll time-first attendance draft flow.

P10 stores explicit Talent input in ``bot_conversations`` but does not submit a
PMO request. These helpers only choose a proposal compatible with the current
gap and render the next concise prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm import proposals
from digital_bast.domain.completion import format_day

if TYPE_CHECKING:
    from digital_bast.bot.attendance_resolution_dm import ResolutionProposal
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft


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


def render_payroll_draft_prompt(
    draft: AttendanceResolutionDraft,
    *,
    prefix: str = "",
) -> str:
    """Render the next missing step without pretending the request was submitted."""
    date_label = format_day(draft.work_date) if draft.work_date is not None else "Attendance ini"
    lines: list[str] = []
    if prefix.strip():
        lines.extend((prefix.strip(), ""))

    if draft.has_proposal:
        lines.append(date_label)
        lines.extend(_draft_value_lines(draft))
        if draft.has_evidence:
            lines.extend(
                (
                    "Bukti: ✓",
                    "",
                    "Informasi tersimpan. Belum diajukan ke PMO.",
                )
            )
        else:
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
