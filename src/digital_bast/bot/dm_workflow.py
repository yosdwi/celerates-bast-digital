"""Regression-safe WhatsApp DM wrapper.

All existing DM behavior still falls through to ``digital_bast.cli`` unchanged.
This wrapper only intercepts an attendance day after its evidence has been
stored and keeps that one day focused until a correction proposal is submitted
to PMO's shared approval queue.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Final

import anyio

from digital_bast import cli
from digital_bast.bot.attendance_resolution import SubmitOutcome
from digital_bast.bot.attendance_resolution_dm import looks_like_resolution_input, proposals
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.operations import (
    create_activation_service,
    create_attendance_evidence_service,
    create_attendance_resolution_dm_state_service,
    create_attendance_resolution_service,
)

_BARE_INDEX_RE: Final = re.compile(r"^\s*\d+\s*$")
_ATTENDANCE_WORDS: Final = ("attendance", "absen", "absensi")


def _resolution_prompt(draft: AttendanceResolutionDraft) -> str:
    if draft.resolution_type.value == "missing_clock_in":
        return (
            "Evidence-nya sudah tersimpan. Clock In masih kosong.\n"
            "Kirim jam masuk yang benar, contoh: `07:30`.\n"
            "Setelah itu pengajuan masuk ke PMO untuk approval."
        )
    if draft.resolution_type.value == "missing_clock_out":
        return (
            "Evidence-nya sudah tersimpan. Clock Out masih kosong.\n"
            "Kirim jam pulang yang benar, contoh: `17:00`.\n"
            "Setelah itu pengajuan masuk ke PMO untuk approval."
        )
    return (
        "Evidence-nya sudah tersimpan. Clock In dan Clock Out masih kosong.\n"
        "Kalau kamu bekerja, kirim dua jam: `07:30 17:00`.\n"
        "Kalau tidak masuk, kirim salah satu: `cuti`, `izin`, atau `sakit`.\n"
        "Setelah itu pengajuan masuk ke PMO untuk approval."
    )


def _should_check_draft(text: str) -> bool:
    lowered = text.casefold()
    return (
        looks_like_resolution_input(text)
        or bool(_BARE_INDEX_RE.fullmatch(text))
        or any(word in lowered for word in _ATTENDANCE_WORDS)
    )


async def _submit_resolution(text: str, jid: str, draft: AttendanceResolutionDraft) -> str:
    parsed = proposals(text)
    if not parsed:
        return _resolution_prompt(draft)

    resolutions = create_attendance_resolution_service()
    state = create_attendance_resolution_dm_state_service()
    last_outcome = SubmitOutcome.INVALID_REQUEST
    for proposal in parsed:
        result = await resolutions.submit(
            draft.employee_id,
            draft.attendance_key,
            jid,
            proposal.resolution_type,
            proposed_check_in=proposal.proposed_check_in,
            proposed_check_out=proposal.proposed_check_out,
            absence_type=proposal.absence_type,
        )
        last_outcome = result.outcome
        if result.outcome is SubmitOutcome.CREATED:
            await state.clear(jid)
            return (
                "✅ Pengajuan koreksi attendance sudah dikirim ke PMO.\n"
                "Status: *Menunggu approval*.\n"
                "Data attendance client asli tidak diubah."
            )
        if result.outcome is SubmitOutcome.ALREADY_OPEN:
            await state.clear(jid)
            return "Pengajuan untuk attendance ini sudah ada dan sedang/ sudah direview PMO."
        if result.outcome in (SubmitOutcome.NOT_FOUND, SubmitOutcome.NOT_OWNED):
            await state.clear(jid)
            return "Attendance ini sudah tidak bisa diproses dari sesi ini. Kirim `attendance` untuk cek ulang."
        if result.outcome is SubmitOutcome.EVIDENCE_REQUIRED:
            return "Evidence belum tersimpan. Pilih attendance-nya lagi lalu kirim foto/dokumen evidence."
        # INVALID_REQUEST and SOURCE_NOT_ELIGIBLE intentionally fall through
        # to the next ordered proposal. Example: one clock value first tries
        # missing Clock In, then missing Clock Out; the immutable source row
        # decides which proposal is actually eligible.

    if last_outcome is SubmitOutcome.SOURCE_NOT_ELIGIBLE:
        await state.clear(jid)
        return (
            "Data attendance client sudah berubah atau koreksinya tidak cocok dengan gap saat ini. "
            "Kirim `attendance` untuk refresh."
        )
    return _resolution_prompt(draft)


async def reply(text: str, jid: str) -> str:
    if not _should_check_draft(text):
        return cli.bot_reply(text, jid=jid, channel="dm")

    state = create_attendance_resolution_dm_state_service()
    draft = await state.pending(jid)
    if draft is None:
        return cli.bot_reply(text, jid=jid, channel="dm")

    activation = create_activation_service()
    bound_employee_id = await activation.resolve(jid)
    if bound_employee_id != draft.employee_id:
        await state.clear(jid)
        return cli.bot_reply(text, jid=jid, channel="dm")

    if looks_like_resolution_input(text):
        return await _submit_resolution(text, jid, draft)

    # While a correction draft is open, a bare index or another `attendance`
    # command must not silently select a different day and overwrite the
    # current target. Other unrelated messages (greeting, tasklist, etc.)
    # continue through the legacy DM flow unchanged.
    if _BARE_INDEX_RE.fullmatch(text) or any(
        word in text.casefold() for word in _ATTENDANCE_WORDS
    ):
        return _resolution_prompt(draft)
    return cli.bot_reply(text, jid=jid, channel="dm")


async def evidence(jid: str, file_path: Path, caption: str) -> str:
    state = create_attendance_resolution_dm_state_service()
    existing = await state.pending(jid)
    if existing is not None:
        # Never let another photo fall through into Task List evidence while
        # an attendance correction is waiting for its clock/absence answer.
        return _resolution_prompt(existing)

    activation = create_activation_service()
    employee_id = await activation.resolve(jid)
    attendance = create_attendance_evidence_service()
    pending_attendance_key = await attendance.pending_attendance(jid)

    legacy_reply = await cli.bot_evidence(jid, file_path, caption)
    if employee_id is None or pending_attendance_key is None:
        return legacy_reply

    # Legacy attendance evidence intentionally remains the storage path. It
    # clears pending_attendance_id after a successful upload; mark_evidence_ready
    # restores that selected row only when evidence really exists and the raw
    # client row still has a clock gap. Task evidence is therefore untouched.
    draft = await state.mark_evidence_ready(jid, employee_id, pending_attendance_key)
    if draft is None:
        return legacy_reply
    return f"{legacy_reply}\n\n{_resolution_prompt(draft)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digital-bast-dm")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reply_parser = subparsers.add_parser("reply")
    _ = reply_parser.add_argument("--text", required=True)
    _ = reply_parser.add_argument("--jid", required=True)
    evidence_parser = subparsers.add_parser("evidence")
    _ = evidence_parser.add_argument("--jid", required=True)
    _ = evidence_parser.add_argument("--file", required=True)
    _ = evidence_parser.add_argument("--caption", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "reply":
        print(anyio.run(reply, str(args.text), str(args.jid)))
        return 0
    print(anyio.run(evidence, str(args.jid), Path(str(args.file)), str(args.caption)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
