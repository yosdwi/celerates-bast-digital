"""Explicit Payroll attendance draft review/submit orchestration.

P13 is the first point where a time-first Payroll draft may create an existing
``attendance_resolution_requests`` row. Submission stays explicit: a complete
draft is never auto-submitted merely because evidence exists. After submit, the
stable reminder snapshot is revalidated through the P09 routing service before
offering the Talent a small continue/stop decision.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from digital_bast.bot.attendance_reminder import (
    ATTENDANCE_REMINDER_LATER_ACTION_ID,
    ATTENDANCE_REMINDER_START_ACTION_ID,
)
from digital_bast.bot.attendance_reminder_routing import AttendanceReminderRouteStatus
from digital_bast.bot.attendance_resolution import SubmitOutcome
from digital_bast.bot.interactive import interactive
from digital_bast.bot.payroll_attendance_draft import render_payroll_draft_prompt

if TYPE_CHECKING:
    from datetime import datetime, time

    from digital_bast.bot.attendance_context import AttendanceReminderContext
    from digital_bast.bot.attendance_reminder_routing import AttendanceReminderRouteResult
    from digital_bast.bot.attendance_resolution import (
        AbsenceType,
        ResolutionType,
        SubmitResult,
    )
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft


class AttendanceResolutionSubmitter(Protocol):
    async def submit(
        self,
        employee_id: str,
        attendance_key: str,
        requested_by_jid: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: AbsenceType | None = None,
    ) -> SubmitResult: ...


class AttendanceDraftState(Protocol):
    async def begin(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft | None: ...

    async def clear(self, wa_jid: str) -> None: ...


class AttendanceContextStore(Protocol):
    async def clear(self, wa_jid: str) -> None: ...


class AttendanceNextGapRouter(Protocol):
    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult: ...


async def edit_payroll_attendance_draft(
    *,
    jid: str,
    draft: AttendanceResolutionDraft,
    state: AttendanceDraftState,
) -> str:
    """Re-open the same source gap, clearing only the proposed correction values."""
    reset = await state.begin(jid, draft.employee_id, draft.attendance_key)
    if reset is None:
        await state.clear(jid)
        return (
            "Data attendance barusan berubah, jadi informasi lama tidak dipakai. "
            "Balas `lengkapi` lagi untuk memuat kondisi terbaru."
        )
    return render_payroll_draft_prompt(
        reset,
        prefix="Oke, silakan ubah informasi attendance.",
    )


async def _continue_to_next_gap(
    *,
    jid: str,
    employee_id: str,
    context: AttendanceReminderContext,
    now: datetime,
    context_store: AttendanceContextStore,
    routing: AttendanceNextGapRouter,
    prefix: str,
    no_action_message: str,
) -> str:
    routed = await routing.first_actionable(
        context,
        employee_id=employee_id,
        now=now,
    )
    if (
        routed.status is AttendanceReminderRouteStatus.OPEN
        and routed.selection is not None
    ):
        remaining = routed.selection.remaining_actionable
        body = (
            f"{prefix}\n\n"
            f"Masih ada {remaining} tanggal yang perlu kamu lengkapi. Mau lanjut sekarang?"
        )
        return interactive(
            body,
            (ATTENDANCE_REMINDER_START_ACTION_ID, "Lanjut"),
            (ATTENDANCE_REMINDER_LATER_ACTION_ID, "Selesai dulu"),
            footer="Payroll Attendance",
        )

    await context_store.clear(jid)
    if routed.status is AttendanceReminderRouteStatus.NO_ACTION:
        return f"{prefix}\n\n{no_action_message}"
    return f"{prefix}\n\nKonteks reminder sudah berubah. Tidak ada action lanjutan dari sesi ini."


async def submit_payroll_attendance_draft(
    *,
    jid: str,
    draft: AttendanceResolutionDraft,
    context: AttendanceReminderContext,
    now: datetime,
    resolutions: AttendanceResolutionSubmitter,
    state: AttendanceDraftState,
    context_store: AttendanceContextStore,
    routing: AttendanceNextGapRouter,
) -> str:
    """Submit one complete draft, then offer continuation from the stable snapshot."""
    if not draft.has_proposal or not draft.has_evidence:
        return render_payroll_draft_prompt(draft)

    result = await resolutions.submit(
        draft.employee_id,
        draft.attendance_key,
        jid,
        draft.resolution_type,
        proposed_check_in=draft.proposed_check_in,
        proposed_check_out=draft.proposed_check_out,
        absence_type=draft.absence_type,
    )

    if result.outcome in {SubmitOutcome.CREATED, SubmitOutcome.ALREADY_OPEN}:
        await state.clear(jid)
        prefix = (
            "✅ Informasi attendance sudah diajukan ke PMO. Status: menunggu review."
            if result.outcome is SubmitOutcome.CREATED
            else "Pengajuan attendance ini sudah ada dan sedang menunggu review PMO."
        )
        return await _continue_to_next_gap(
            jid=jid,
            employee_id=draft.employee_id,
            context=context,
            now=now,
            context_store=context_store,
            routing=routing,
            prefix=prefix,
            no_action_message=(
                "Tidak ada action Talent lain dari reminder ini sekarang. "
                "Pengajuan yang sudah masuk tetap menunggu review PMO."
            ),
        )

    if result.outcome is SubmitOutcome.EVIDENCE_REQUIRED:
        return (
            "Bukti attendance tidak ditemukan lagi. "
            "Kirim ulang screenshot/dokumen untuk draft ini sebelum diajukan."
        )

    if result.outcome is SubmitOutcome.SOURCE_NOT_ELIGIBLE:
        await state.clear(jid)
        return await _continue_to_next_gap(
            jid=jid,
            employee_id=draft.employee_id,
            context=context,
            now=now,
            context_store=context_store,
            routing=routing,
            prefix="Data attendance berubah sebelum pengajuan, jadi informasi lama tidak diajukan.",
            no_action_message="Tidak ada action Talent lain dari reminder ini sekarang.",
        )

    if result.outcome is SubmitOutcome.NOT_OWNED:
        await state.clear(jid)
        await context_store.clear(jid)
        return "Attendance ini tidak lagi cocok dengan identity WhatsApp aktif. Hubungi admin."

    await state.clear(jid)
    return (
        "Draft attendance ini sudah tidak bisa diajukan dari kondisi sekarang. "
        "Balas `lengkapi` lagi untuk memuat data terbaru."
    )
