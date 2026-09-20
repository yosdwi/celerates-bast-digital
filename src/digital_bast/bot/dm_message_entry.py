"""Timestamp-aware DM entry for natural Payroll attendance replies.

The existing deterministic DM workflow remains the authority. This wrapper only
intercepts an already-active Payroll draft when a message explicitly references a
date or when deterministic proposal parsing cannot understand a natural attendance
sentence. All button/action/numeric paths delegate unchanged.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

import anyio

from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import AttendanceReminderRouteStatus
from digital_bast.bot.attendance_reminder_runtime import (
    create_attendance_reminder_context_service,
    create_attendance_reminder_routing_service,
)
from digital_bast.bot.attendance_resolution_dm import ResolutionProposal
from digital_bast.bot.attendance_resolution_dm_state import (
    AttendanceResolutionDmStateService,
    AttendanceResolutionDraft,
)
from digital_bast.bot.dm_entry import reply as legacy_entry_reply
from digital_bast.bot.dm_workflow import reply as workflow_reply
from digital_bast.bot.payroll_attendance_draft import (
    parse_payroll_draft_command,
    render_payroll_draft_prompt,
    select_payroll_proposal,
)
from digital_bast.bot.payroll_attendance_natural import (
    ExplicitWorkDate,
    explicit_work_date,
    looks_like_natural_attendance_input,
    proposal_for_active_gap,
)
from digital_bast.bot.payroll_attendance_natural_runtime import (
    create_payroll_attendance_natural_interpreter,
)
from digital_bast.bot.payroll_attendance_repeat import parse_payroll_repeat_command
from digital_bast.domain.completion import format_day
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import create_attendance_resolution_dm_state_service


def _parse_message_at(raw: str) -> datetime:
    normalized = raw.strip().replace("Z", "+00:00")
    value = datetime.fromisoformat(normalized)
    if value.tzinfo is None:
        raise ValueError("message timestamp must include timezone")
    return value.astimezone(UTC)


def _date_mismatch_reply(draft_date: date, reference: ExplicitWorkDate) -> str:
    active_label = format_day(draft_date)
    if reference.work_date is None:
        detail = "Tanggal di pesanmu belum bisa dipastikan dengan aman."
    else:
        detail = f"Pesanmu menyebut {format_day(reference.work_date)}, bukan {active_label}."
    return (
        f"{detail} Aku belum menyimpan perubahan apa pun.\n\n"
        f"Sesi yang sedang dibuka: {active_label}."
    )


async def _active_payroll_draft(
    jid: str,
) -> tuple[
    AttendanceResolutionDmStateService,
    AttendanceResolutionDraft | None,
    AttendanceReminderContext | None,
]:
    state = create_attendance_resolution_dm_state_service()
    draft = await state.pending(jid)
    if draft is None or draft.work_date is None:
        return state, draft, None
    context = await create_attendance_reminder_context_service().load(jid)
    if (
        context is None
        or context.employee_id != draft.employee_id
        or draft.attendance_key not in context.attendance_keys
    ):
        return state, draft, None
    return state, draft, context


async def _revalidate_exact_gap(
    draft: AttendanceResolutionDraft,
    context: AttendanceReminderContext,
    message_at: datetime,
) -> bool:
    routed = await create_attendance_reminder_routing_service().first_actionable(
        context,
        employee_id=draft.employee_id,
        now=message_at.astimezone(JAKARTA),
    )
    return bool(
        routed.status is AttendanceReminderRouteStatus.OPEN
        and routed.selection is not None
        and routed.selection.day.attendance_key == draft.attendance_key
    )


async def _save_proposal(
    jid: str,
    state: AttendanceResolutionDmStateService,
    draft: AttendanceResolutionDraft,
    context: AttendanceReminderContext,
    proposal: ResolutionProposal,
    message_at: datetime,
) -> str:
    if not await _revalidate_exact_gap(draft, context, message_at):
        await state.clear(jid)
        return (
            "Kondisi attendance sudah berubah, jadi informasi ini belum disimpan. "
            "Balas `lengkapi` lagi dari reminder yang masih aktif untuk memuat kondisi terbaru."
        )
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
            "Data attendance barusan berubah, jadi draft ini tidak disimpan. "
            "Balas `lengkapi` lagi untuk memuat kondisi terbaru."
        )
    return render_payroll_draft_prompt(
        saved,
        prefix="Oke, informasi attendance sudah tersimpan.",
    )


async def reply(text: str, jid: str, message_at: datetime) -> str:  # noqa: PLR0911
    state, draft, context = await _active_payroll_draft(jid)
    if draft is None or context is None or draft.work_date is None:
        return await legacy_entry_reply(text, jid)

    # Existing explicit state-machine commands always win. Do not let natural
    # interpretation shadow Same/Different or Ajukan/Ubah numeric/button actions.
    if not draft.has_proposal and parse_payroll_repeat_command(text) is not None:
        return await workflow_reply(text, jid)
    if draft.has_proposal and draft.has_evidence and parse_payroll_draft_command(text) is not None:
        return await workflow_reply(text, jid)

    deterministic = select_payroll_proposal(draft, text)
    reference = explicit_work_date(
        text,
        message_at=message_at,
        active_work_date=draft.work_date,
    )
    if deterministic is not None:
        if not reference.mentioned:
            return await workflow_reply(text, jid)
        if reference.work_date != draft.work_date:
            return _date_mismatch_reply(draft.work_date, reference)
        return await _save_proposal(jid, state, draft, context, deterministic, message_at)

    if not looks_like_natural_attendance_input(text):
        return await workflow_reply(text, jid)
    interpreter = create_payroll_attendance_natural_interpreter()
    if interpreter is None:
        return await workflow_reply(text, jid)
    candidate = await interpreter.interpret(
        text,
        message_at=message_at,
        active_work_date=draft.work_date,
        active_resolution_type=draft.resolution_type,
    )
    if candidate is None:
        return await workflow_reply(text, jid)
    proposal = proposal_for_active_gap(
        candidate,
        active_work_date=draft.work_date,
        active_resolution_type=draft.resolution_type,
    )
    if proposal is None:
        candidate_reference = ExplicitWorkDate(candidate.work_date is not None, candidate.work_date)
        if candidate_reference.mentioned and candidate_reference.work_date != draft.work_date:
            return _date_mismatch_reply(draft.work_date, candidate_reference)
        return render_payroll_draft_prompt(draft)
    return await _save_proposal(jid, state, draft, context, proposal, message_at)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digital-bast-dm-message-entry")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reply_parser = subparsers.add_parser("reply")
    _ = reply_parser.add_argument("--text", required=True)
    _ = reply_parser.add_argument("--jid", required=True)
    _ = reply_parser.add_argument("--message-at", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "reply":  # pragma: no cover - argparse invariant
        return 2
    try:
        message_at = _parse_message_at(args.message_at)
    except ValueError:
        # Invalid transport metadata must not make a valid user message fail.
        result = anyio.run(legacy_entry_reply, args.text, args.jid)
    else:
        result = anyio.run(reply, args.text, args.jid, message_at)
    _ = sys.stdout.write(f"{result}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
