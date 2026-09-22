"""BAST-closing entry into the existing attendance-correction workflow.

BAST owns only the bounded reminder scope (employee + calendar-month period).
Once one exact date is selected, this module seeds the existing durable
AttendanceReminderContext with that single canonical attendance identity. From
that point evidence, edit/review, PMO submission and source revalidation all use
the same production Attendance workflow as Payroll. Raw attendance is never
mutated here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from digital_bast.application.attendance_closing_policy import payroll_cycle_for
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_runtime import (
    create_attendance_reminder_context_service,
)
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
from digital_bast.domain.completion import DateRange, format_day
from digital_bast.operations import (
    completion_status,
    create_attendance_evidence_service,
    create_attendance_resolution_dm_state_service,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from digital_bast.bot.attendance_evidence import AttendanceEvidenceCandidate
    from digital_bast.bot.bast_reminder_context import BastReminderContext


def _period(context: BastReminderContext) -> DateRange:
    return DateRange(context.period_start, context.period_end)


async def _candidate_for_date(
    employee_id: str,
    period: DateRange,
    work_date: date,
) -> AttendanceEvidenceCandidate | None:
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


async def _seed_canonical_attendance_context(
    *,
    jid: str,
    context: BastReminderContext,
    attendance_key: str,
    work_date: date,
) -> None:
    """Hand one exact BAST gap to the already-existing Payroll draft machinery.

    ``payroll_cycle_for`` is used only because AttendanceReminderContext stores
    its canonical cycle identity for later source revalidation. The BAST scope
    remains the calendar-month period stored in BastReminderContext; the seeded
    context contains exactly one attendance key, so it cannot expand the BAST
    selection into unrelated Payroll dates.
    """
    cycle = payroll_cycle_for(work_date)
    stable = AttendanceReminderContext.create(
        employee_id=context.employee_id,
        cycle_id=cycle.cycle_id,
        attendance_keys=(attendance_key,),
        expires_at=context.expires_at,
    )
    await create_attendance_reminder_context_service().save(jid, stable)


async def natural_bast_attendance_reply(  # noqa: C901, PLR0911 - explicit fail-closed routing
    *,
    text: str,
    jid: str,
    message_at: datetime,
    context: BastReminderContext,
) -> str | None:
    """Bootstrap/fill one exact BAST attendance draft from natural text.

    The requested date is constrained to the durable BAST reminder period and is
    re-read from current completion facts before ``begin``. ``begin`` and
    ``save_proposal`` then revalidate ownership/source-gap state under DB locks.
    After the exact identity is known, a single-key AttendanceReminderContext is
    saved so all subsequent evidence/review/submit steps use the canonical
    Attendance flow rather than a BAST-specific state machine.
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

    await _seed_canonical_attendance_context(
        jid=jid,
        context=context,
        attendance_key=draft.attendance_key,
        work_date=target_date,
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
        await create_attendance_reminder_context_service().clear(jid)
        return (
            "Kondisi attendance berubah sebelum informasi disimpan. "
            "Tidak ada perubahan yang diajukan; coba lagi dari status terbaru."
        )
    return render_payroll_draft_prompt(
        saved,
        prefix="Oke, informasi attendance sudah tersimpan.",
    )
