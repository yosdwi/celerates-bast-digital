"""BAST-closing entry into the existing attendance-correction workflow.

BAST owns only the bounded reminder scope (employee + calendar-month period).
The actual correction draft, evidence upload and PMO request continue to use the
same attendance services as Payroll.  No raw attendance field is mutated here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from digital_bast.bast_runtime import create_bast_snapshot_service
from digital_bast.bot.bast_reminder_context import BastReminderContextService
from digital_bast.bot.payroll_attendance_draft import (
    render_payroll_draft_prompt,
    select_payroll_proposal,
)
from digital_bast.bot.payroll_attendance_natural import (
    explicit_work_date_for_period,
    proposal_for_active_gap,
)
from digital_bast.bot.payroll_attendance_natural_runtime import (
    create_payroll_attendance_natural_interpreter,
)
from digital_bast.config import get_settings
from digital_bast.domain.completion import DateRange, format_day
from digital_bast.operations import (
    completion_status,
    create_attendance_evidence_service,
    create_attendance_resolution_dm_state_service,
    create_attendance_resolution_service,
)
from digital_bast.bot.attendance_resolution import SubmitOutcome

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
    from digital_bast.bot.bast_reminder_context import BastReminderContext


def _dsn() -> str | None:
    try:
        settings = get_settings()
    except (OSError, ValueError):
        return None
    return None if settings.database_dsn is None else settings.database_dsn.get_secret_value()


def _period(context: BastReminderContext) -> DateRange:
    return DateRange(context.period_start, context.period_end)


async def is_bast_attendance_draft(jid: str, draft: AttendanceResolutionDraft) -> bool:
    """Return True only when the open draft belongs to the active BAST reminder."""
    if draft.work_date is None:
        return False
    dsn = _dsn()
    if dsn is None:
        return False
    context = await BastReminderContextService(dsn).load(jid)
    if context is None or "attendance" not in context.domains:
        return False
    period = _period(context)
    return (
        context.employee_id == draft.employee_id
        and period.start <= draft.work_date <= period.end
    )


async def _candidate_for_date(
    employee_id: str,
    period: DateRange,
    work_date: date,
):
    report = await completion_status(period)
    mine = next(
        (item for item in report.employees if item.employee_id == employee_id),
        None,
    )
    if mine is None:
        return None

    attendance = create_attendance_evidence_service()
    evidence_days = frozenset(mine.log_1_pama_evidence_days)
    missing_days = frozenset(mine.log_1_pama_missing_data_days)
    if work_date in evidence_days:
        rows = await attendance.list_candidates(employee_id, frozenset({work_date}))
        return rows[0] if len(rows) == 1 else None
    if work_date in missing_days:
        rows = await attendance.list_missing(employee_id, frozenset({work_date}))
        if len(rows) != 1:
            return None
        await attendance.ensure_manual(employee_id, work_date)
        return rows[0]
    return None


async def natural_bast_attendance_reply(
    *,
    text: str,
    jid: str,
    message_at: datetime,
    context: BastReminderContext,
) -> str | None:
    """Bootstrap/fill one exact BAST attendance draft from natural text.

    The requested date is constrained to the durable BAST reminder period and is
    re-read from current completion facts before ``begin``.  ``begin`` and
    ``save_proposal`` then revalidate ownership/source-gap state under DB locks.
    """
    period = _period(context)
    state = create_attendance_resolution_dm_state_service()
    active = await state.pending(jid)
    active_date = (
        active.work_date
        if active is not None
        and active.employee_id == context.employee_id
        and active.work_date is not None
        and period.start <= active.work_date <= period.end
        else None
    )

    reference = explicit_work_date_for_period(
        text,
        message_at=message_at,
        period_start=period.start,
        period_end=period.end,
    )
    if reference.mentioned and reference.work_date is None:
        return (
            "Tanggal di pesanmu belum bisa dipastikan dengan aman. "
            "Sebut tanggalnya lengkap, misalnya `18 September pulang 17:30`."
        )
    target_date = reference.work_date if reference.mentioned else active_date
    if target_date is None:
        return (
            "Attendance yang mana? Sebut tanggalnya langsung, misalnya "
            "`18 September pulang 17:30` atau `18 September cuti`."
        )

    if active is not None and active_date == target_date:
        draft = active
    else:
        candidate = await _candidate_for_date(context.employee_id, period, target_date)
        if candidate is None:
            return (
                f"{format_day(target_date)} tidak termasuk attendance yang masih perlu action "
                "dari BAST periode ini. Status terbaru sudah dimuat ulang."
            )
        draft = await state.begin(jid, context.employee_id, candidate.attendance_key)
        if draft is None:
            return (
                "Data attendance barusan berubah, jadi belum ada informasi yang disimpan. "
                "Coba lagi setelah status terbaru dimuat."
            )

    proposal = select_payroll_proposal(draft, text)
    if proposal is None:
        interpreter = create_payroll_attendance_natural_interpreter()
        if interpreter is not None:
            candidate = await interpreter.interpret(
                text,
                message_at=message_at,
                active_work_date=draft.work_date,
                active_resolution_type=draft.resolution_type,
            )
            if candidate is not None:
                proposal = proposal_for_active_gap(
                    candidate,
                    active_work_date=draft.work_date,
                    active_resolution_type=draft.resolution_type,
                )

    if proposal is None:
        return render_payroll_draft_prompt(draft)

    saved = await state.save_proposal(
        jid,
        draft.employee_id,
        draft.attendance_key,
        proposal.resolution_type,
        proposed_check_in=proposal.proposed_check_in,
        proposed_check_out=proposal.proposed_check_out,
        absence_type=proposal.absence_type,
    )
    if saved is None:
        await state.clear(jid)
        return (
            "Kondisi attendance berubah sebelum informasi disimpan. "
            "Tidak ada perubahan yang diajukan; coba lagi dari status terbaru."
        )
    return render_payroll_draft_prompt(
        saved,
        prefix="Oke, informasi attendance sudah tersimpan.",
    )


async def submit_bast_attendance_draft(
    *,
    jid: str,
    draft: AttendanceResolutionDraft,
    now: datetime | None = None,
) -> str:
    """Submit a complete BAST-started draft through the canonical PMO request service."""
    if not draft.has_proposal or not draft.has_evidence:
        return render_payroll_draft_prompt(draft)

    dsn = _dsn()
    if dsn is None:
        return "BAST Closing sedang tidak dapat memverifikasi sesi attendance ini."
    contexts = BastReminderContextService(dsn)
    instant = now or datetime.now(UTC)
    context = await contexts.load(jid, now=instant)
    if (
        context is None
        or "attendance" not in context.domains
        or context.employee_id != draft.employee_id
        or draft.work_date is None
    ):
        return "Sesi BAST attendance ini sudah tidak aktif. Buka reminder BAST terbaru."
    period = _period(context)
    if not period.start <= draft.work_date <= period.end:
        return "Attendance ini berada di luar periode BAST yang sedang aktif."

    state = create_attendance_resolution_dm_state_service()
    result = await create_attendance_resolution_service().submit(
        draft.employee_id,
        draft.attendance_key,
        jid,
        draft.resolution_type,
        proposed_check_in=draft.proposed_check_in,
        proposed_check_out=draft.proposed_check_out,
        absence_type=draft.absence_type,
    )
    if result.outcome is SubmitOutcome.EVIDENCE_REQUIRED:
        return "Bukti attendance belum ditemukan. Kirim bukti untuk draft ini sebelum diajukan."
    if result.outcome is SubmitOutcome.SOURCE_NOT_ELIGIBLE:
        await state.clear(jid)
        return (
            "Data attendance berubah sebelum pengajuan, jadi informasi lama tidak diajukan. "
            "Buka status BAST terbaru untuk melanjutkan."
        )
    if result.outcome is SubmitOutcome.NOT_OWNED:
        await state.clear(jid)
        await contexts.clear(jid)
        return "Attendance ini tidak lagi cocok dengan identity WhatsApp aktif. Hubungi admin."
    if result.outcome not in {SubmitOutcome.CREATED, SubmitOutcome.ALREADY_OPEN}:
        await state.clear(jid)
        return "Draft attendance ini sudah tidak dapat diajukan dari kondisi sekarang."

    await state.clear(jid)
    prefix = (
        "✅ Informasi attendance sudah diajukan ke PMO. Status: menunggu review."
        if result.outcome is SubmitOutcome.CREATED
        else "Pengajuan attendance ini sudah ada dan sedang menunggu review PMO."
    )

    snapshot = await create_bast_snapshot_service().build(period)
    talent = next(
        (item for item in snapshot.talents if item.employee_id == draft.employee_id),
        None,
    )
    if talent is None or not talent.actionable:
        return (
            f"{prefix}\n\nTidak ada action Talent lain yang terdeteksi dari BAST saat ini. "
            "Pengajuan attendance tetap menunggu review PMO."
        )

    labels = {
        "attendance": "Attendance",
        "timesheet": "Timesheet",
        "task": "Task List",
        "evidence": "Evidence",
    }
    lines = [prefix, "", "Masih ada bagian BAST yang perlu kamu tindaklanjuti:"]
    lines.extend(
        f"• {labels.get(item.domain, item.domain.title())} — {max(len(item.issues), 1)}"
        for item in talent.actionable
    )
    lines.extend(("", "Balas nama bagiannya atau pilih dari reminder BAST terbaru."))
    return "\n".join(lines)
