"""Regression-safe WhatsApp DM wrapper.

All existing DM behavior falls through to ``digital_bast.cli`` unchanged until
an attendance evidence upload opens a correction draft. Once that draft exists,
its selected attendance row is kept focused until a proposal is submitted to
PMO's shared approval queue. The wrapper also owns the approval-aware attendance
summary so a submitted correction is shown as "menunggu PMO", never as another
upload candidate or as falsely complete.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import anyio
from anyio.to_thread import run_sync

from digital_bast import cli
from digital_bast.bot.attendance_resolution import (
    ResolutionStatus,
    ResolutionType,
    SubmitOutcome,
)
from digital_bast.bot.attendance_resolution_dm import looks_like_resolution_input, proposals
from digital_bast.bot.whatsapp import GROUP_ONLY_DM_INTENTS, parse_command, strip_mentions
from digital_bast.domain.completion import DateRange, format_day
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import (
    completion_status,
    create_activation_service,
    create_attendance_evidence_service,
    create_attendance_resolution_dm_state_service,
    create_attendance_resolution_service,
)

if TYPE_CHECKING:
    from digital_bast.bot.attendance_evidence import AttendanceEvidenceCandidate
    from digital_bast.bot.attendance_resolution import AttendanceResolution
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
    from digital_bast.domain.completion import EmployeeCompletion


type DmCommand = Literal["reply", "evidence"]

_ATTENDANCE_WORDS: Final = ("attendance", "absen", "absensi")


class DmArguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.command: DmCommand = "reply"
        self.text: str = ""
        self.jid: str = ""
        self.file: str = ""
        self.caption: str = ""


def _resolution_prompt(draft: AttendanceResolutionDraft) -> str:
    if draft.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return (
            "Evidence-nya sudah tersimpan. Clock In masih kosong.\n"
            "Kirim jam masuk yang benar, contoh: `07:30`.\n"
            "Setelah itu pengajuan masuk ke PMO untuk approval."
        )
    if draft.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
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


def _legacy_dm_reply(text: str, jid: str) -> str:
    """Run the unchanged synchronous CLI DM entrypoint outside our event loop."""
    return cli.bot_reply(text, jid=jid, channel="dm")


def _wants_attendance_summary(text: str) -> bool:
    normalized = strip_mentions(text)
    lowered = normalized.strip().casefold()
    if not any(word in lowered for word in _ATTENDANCE_WORDS):
        return False
    today = datetime.now(JAKARTA).date()
    return parse_command(normalized, today).intent not in GROUP_ONLY_DM_INTENTS


def _time_label(value: object) -> str:
    return value.strftime("%H:%M") if hasattr(value, "strftime") else "?"


def _resolution_description(request: AttendanceResolution) -> str:
    if request.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return f"Clock In → {_time_label(request.proposed_check_in)}"
    if request.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return f"Clock Out → {_time_label(request.proposed_check_out)}"
    if request.resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return (
            f"Clock In {_time_label(request.proposed_check_in)} · "
            f"Clock Out {_time_label(request.proposed_check_out)}"
        )
    absence = request.absence_type.value.capitalize() if request.absence_type is not None else "Absen"
    return absence


def _latest_rejections(
    requests: tuple[AttendanceResolution, ...], period: DateRange
) -> dict[int, AttendanceResolution]:
    latest: dict[int, AttendanceResolution] = {}
    for request in requests:
        if request.status is not ResolutionStatus.REJECTED:
            continue
        if not period.start <= request.work_date <= period.end:
            continue
        latest.setdefault(request.attendance_id, request)
    return latest


def _format_approval_aware_attendance(
    mine: EmployeeCompletion,
    period: DateRange,
    candidates: tuple[AttendanceEvidenceCandidate, ...],
    pending: tuple[AttendanceResolution, ...],
    rejections: dict[int, AttendanceResolution],
) -> str:
    belum_lengkap = len(mine.log_1_pama.issues)
    lengkap = max(mine.total_work_days - belum_lengkap, 0)
    lines = [
        f"*Attendance kamu — {period.label()}*",
        "",
        f"{'Total':<13}: {mine.total_work_days}",
        f"{'Lengkap':<13}: {lengkap}",
        f"{'Belum Lengkap':<13}: {belum_lengkap}",
        f"{'Perlu evidence':<13}: {len(candidates)} hari",
        f"{'Menunggu PMO':<13}: {len(pending)} hari",
    ]
    if pending:
        lines.extend(("", "Menunggu approval PMO:"))
        lines.extend(
            f"• {format_day(request.work_date)} — {_resolution_description(request)}"
            for request in pending
        )
    if candidates:
        lines.extend(("", "Perlu evidence / diajukan ulang:"))
        for index, candidate in enumerate(candidates, start=1):
            rejected = rejections.get(candidate.evidence_count)
            suffix = ""
            if rejected is not None and rejected.rejection_reason:
                suffix = f" — ditolak PMO: {rejected.rejection_reason}"
            lines.append(f"{index}. {format_day(candidate.work_date)}{suffix}")
        lines.extend(
            (
                "",
                "Balas nomornya, lalu kirim foto/dokumen evidence-nya.",
                "Tips: kirim sebagai *Dokumen* supaya gambar tidak dikompres WhatsApp.",
            )
        )
    if mine.log_1_pama_missing_data_days:
        lines.extend(("", "Data attendance belum masuk sistem (bukan masalah evidence):"))
        lines.extend(f"• {format_day(day)}" for day in mine.log_1_pama_missing_data_days)
        lines.append("Hubungi admin untuk cek pipeline/sinkronisasi data.")
    if not candidates and not pending and not mine.log_1_pama_missing_data_days:
        lines.append("")
        lines.append("Attendance kamu bulan ini lengkap ✅")
    return "\n".join(lines).strip()


async def _attendance_status_reply(employee_id: str, jid: str) -> str:
    today = datetime.now(JAKARTA).date()
    period = DateRange(today.replace(day=1), today)
    report = await completion_status(period)
    mine = next((item for item in report.employees if item.employee_id == employee_id), None)
    if mine is None:
        return "Attendance kamu belum tersedia di sistem."

    attendance = create_attendance_evidence_service()
    candidates: tuple[AttendanceEvidenceCandidate, ...] = ()
    if mine.log_1_pama_evidence_days:
        candidates = await attendance.list_candidates(
            employee_id, frozenset(mine.log_1_pama_evidence_days)
        )
    if candidates:
        await attendance.mark_active(jid)

    requests = await create_attendance_resolution_service().for_employee(employee_id)
    pending = tuple(
        request
        for request in requests
        if request.status is ResolutionStatus.PENDING
        and period.start <= request.work_date <= period.end
    )
    return _format_approval_aware_attendance(
        mine,
        period,
        candidates,
        pending,
        _latest_rejections(requests, period),
    )


async def _submit_resolution(  # noqa: PLR0911 - explicit workflow outcomes
    text: str, jid: str, draft: AttendanceResolutionDraft
) -> str:
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
            return (
                "Attendance ini sudah tidak bisa diproses dari sesi ini. "
                "Kirim `attendance` untuk cek ulang."
            )
        if result.outcome is SubmitOutcome.EVIDENCE_REQUIRED:
            return (
                "Evidence belum tersimpan. Pilih attendance-nya lagi lalu kirim "
                "foto/dokumen evidence."
            )

    if last_outcome is SubmitOutcome.SOURCE_NOT_ELIGIBLE:
        await state.clear(jid)
        return (
            "Data attendance client sudah berubah atau koreksinya tidak cocok dengan gap saat ini. "
            "Kirim `attendance` untuk refresh."
        )
    return _resolution_prompt(draft)


async def reply(text: str, jid: str) -> str:
    state = create_attendance_resolution_dm_state_service()
    draft = await state.pending(jid)
    if draft is None:
        if _wants_attendance_summary(text):
            activation = create_activation_service()
            employee_id = await activation.resolve(jid)
            if employee_id is not None:
                return await _attendance_status_reply(employee_id, jid)
        return await run_sync(_legacy_dm_reply, text, jid)

    activation = create_activation_service()
    bound_employee_id = await activation.resolve(jid)
    if bound_employee_id != draft.employee_id:
        await state.clear(jid)
        return await run_sync(_legacy_dm_reply, text, jid)

    if looks_like_resolution_input(text):
        return await _submit_resolution(text, jid, draft)
    return _resolution_prompt(draft)


async def evidence(jid: str, file_path: Path, caption: str) -> str:
    state = create_attendance_resolution_dm_state_service()
    existing = await state.pending(jid)
    if existing is not None:
        return _resolution_prompt(existing)

    activation = create_activation_service()
    employee_id = await activation.resolve(jid)
    attendance = create_attendance_evidence_service()
    pending_attendance_key = await attendance.pending_attendance(jid)

    legacy_reply = await cli.bot_evidence(jid, file_path, caption)
    if employee_id is None or pending_attendance_key is None:
        return legacy_reply

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


def _write(text: str) -> None:
    _ = sys.stdout.write(f"{text}\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv, namespace=DmArguments())
    if args.command == "reply":
        _write(anyio.run(reply, args.text, args.jid))
        return 0
    _write(anyio.run(evidence, args.jid, Path(args.file), args.caption))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
