"""Production WhatsApp DM workflow wrapper.

The wrapper keeps legacy Talent task/evidence behavior intact while owning the
new durable business workflows around it: PMO authorization/linking, attendance
resolution approval, and Talent phone-number rebind. WhatsApp remains an
interaction layer only; every button/free-text action is re-authorized and
validated against durable backend state before a mutation happens.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import anyio
from anyio.to_thread import run_sync

from digital_bast import cli
from digital_bast.application.workflow_control import InviteOutcome
from digital_bast.bot.attendance_resolution import (
    ResolutionStatus,
    ResolutionType,
    SubmitOutcome,
)
from digital_bast.bot.attendance_resolution_dm import looks_like_resolution_input, proposals
from digital_bast.bot.interactive import interactive
from digital_bast.bot.pmo_workflow import reply as pmo_reply
from digital_bast.bot.rebind import RebindRequestOutcome
from digital_bast.bot.whatsapp import GROUP_ONLY_DM_INTENTS, parse_command, strip_mentions
from digital_bast.domain.completion import DateRange, format_day
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import (
    completion_status,
    create_activation_service,
    create_attendance_evidence_service,
    create_attendance_resolution_dm_state_service,
    create_attendance_resolution_service,
    create_identity_rebind_service,
    create_rebind_onboarding_service,
    create_workflow_control_service,
)

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.bot.attendance_evidence import AttendanceEvidenceCandidate
    from digital_bast.bot.attendance_resolution import AttendanceResolution
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
    from digital_bast.domain.completion import EmployeeCompletion


type DmCommand = Literal["reply", "evidence"]

_ATTENDANCE_WORDS: Final = ("attendance", "absen", "absensi")
_MENU_WORDS: Final = frozenset({"menu", "halo", "hai", "hi", "start", "help", "bantuan"})
_YES_WORDS: Final = frozenset({"ya", "iya", "yes", "y", "betul", "benar", "yoi", "bener"})
_REBIND_SUBMIT_WORDS: Final = frozenset(
    {"ganti nomor", "ajukan ganti nomor", "rebind", "rebind:submit"}
)
_REBIND_CANCEL_WORDS: Final = frozenset({"batal", "cancel", "rebind:cancel"})


class DmArguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.command: DmCommand = "reply"
        self.text: str = ""
        self.jid: str = ""
        self.file: str = ""
        self.caption: str = ""


def _resolution_prompt(draft: AttendanceResolutionDraft, prefix: str = "") -> str:
    intro = f"{prefix}\n\n" if prefix.strip() else ""
    if draft.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return (
            f"{intro}Evidence-nya sudah tersimpan. Clock In masih kosong.\n"
            "Kirim jam masuk yang benar, contoh: `07:30`.\n"
            "Setelah itu pengajuan masuk ke PMO untuk approval."
        )
    if draft.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return (
            f"{intro}Evidence-nya sudah tersimpan. Clock Out masih kosong.\n"
            "Kirim jam pulang yang benar, contoh: `17:00`.\n"
            "Setelah itu pengajuan masuk ke PMO untuk approval."
        )
    body = (
        f"{intro}Evidence-nya sudah tersimpan. Clock In dan Clock Out masih kosong.\n"
        "Kalau kamu bekerja, kirim dua jam: `07:30 17:00`.\n"
        "Kalau tidak masuk, pilih Cuti, Izin, atau Sakit.\n"
        "Setelah itu pengajuan masuk ke PMO untuk approval."
    )
    return interactive(
        body,
        ("cuti", "Cuti"),
        ("izin", "Izin"),
        ("sakit", "Sakit"),
        footer="Raw attendance client tetap tidak diubah",
    )


def _talent_menu(name: str | None = None) -> str:
    greeting = f"Halo {name}." if name else "Halo."
    return interactive(
        f"{greeting}\nPilih yang mau kamu cek. Kamu juga tetap bisa ketik dengan bahasa biasa.",
        ("attendance", "Attendance"),
        ("tasklist", "Task List"),
        ("evidence", "Evidence Task"),
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


def _time_label(value: time | None) -> str:
    return value.strftime("%H:%M") if value is not None else "?"


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
    absence = (
        request.absence_type.value.capitalize() if request.absence_type is not None else "Absen"
    )
    return absence


def _latest_rejections(
    requests: tuple[AttendanceResolution, ...], period: DateRange
) -> dict[date, AttendanceResolution]:
    latest: dict[date, AttendanceResolution] = {}
    for request in requests:
        if request.status is not ResolutionStatus.REJECTED:
            continue
        if not period.start <= request.work_date <= period.end:
            continue
        latest.setdefault(request.work_date, request)
    return latest


def _format_approval_aware_attendance(
    mine: EmployeeCompletion,
    period: DateRange,
    candidates: tuple[AttendanceEvidenceCandidate, ...],
    pending: tuple[AttendanceResolution, ...],
    rejections: dict[date, AttendanceResolution],
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
            rejected = rejections.get(candidate.work_date)
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
        lines.extend(("", "Attendance kamu bulan ini lengkap ✅"))
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
    text = _format_approval_aware_attendance(
        mine,
        period,
        candidates,
        pending,
        _latest_rejections(requests, period),
    )
    return interactive(
        text,
        ("tasklist", "Task List"),
        ("attendance", "Refresh"),
        ("menu", "Menu"),
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
            return interactive(
                "✅ Pengajuan koreksi attendance sudah dikirim ke PMO.\n"
                "Status: *Menunggu approval*.\n"
                "Data attendance client asli tidak diubah.",
                ("attendance", "Cek Attendance"),
                ("menu", "Menu"),
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


def _mask_jid(jid: str) -> str:
    number = jid.split("@", 1)[0]
    if len(number) <= 6:
        return number
    return f"{number[:3]}***{number[-3:]}"


async def _rebind_prompt(jid: str, employee_id: str) -> str:
    old_jid = await create_rebind_onboarding_service().existing_jid(employee_id)
    old_label = _mask_jid(old_jid) if old_jid else "nomor lama"
    return interactive(
        "NRP ini sudah terhubung ke WhatsApp lain.\n"
        f"Binding aktif: {old_label}\n\n"
        "Kalau ini memang nomor barumu, ajukan ganti nomor. Nomor lama tetap aktif "
        "sampai PMO approve.",
        ("rebind:submit", "Ajukan Ganti Nomor"),
        ("rebind:cancel", "Batal"),
    )


async def _handle_rebind_stage(text: str, jid: str) -> str | None:
    activation = create_activation_service()
    if await activation.resolve(jid) is not None:
        return None
    rebind = create_identity_rebind_service()
    staged = await rebind.staged(jid)
    lowered = text.strip().casefold()

    if staged is not None:
        if lowered in _REBIND_CANCEL_WORDS:
            await rebind.clear_stage(jid)
            return "Oke, pengajuan ganti nomor dibatalkan. Kirim NRP lagi kalau mau mulai ulang."
        if lowered in _REBIND_SUBMIT_WORDS:
            result = await rebind.request(staged, jid)
            if result.outcome in (
                RebindRequestOutcome.CREATED,
                RebindRequestOutcome.ALREADY_PENDING,
            ):
                await rebind.clear_stage(jid)
                return interactive(
                    "✅ Pengajuan ganti nomor sudah masuk ke PMO.\n"
                    "Nomor lama tetap aktif sampai request di-approve.",
                    ("menu", "Selesai"),
                )
            if result.outcome is RebindRequestOutcome.NEW_NUMBER_ALREADY_BOUND:
                return "Nomor ini sudah terhubung ke identity lain dan tidak bisa dipakai untuk rebind."
            if result.outcome is RebindRequestOutcome.SAME_NUMBER:
                await rebind.clear_stage(jid)
                return "Nomor ini ternyata sama dengan binding aktif; tidak perlu ganti nomor."
            await rebind.clear_stage(jid)
            return "Binding lama sudah tidak ditemukan. Kirim NRP lagi untuk onboarding normal."
        return await _rebind_prompt(jid, staged)

    pending_employee_id = await activation.pending_claim(jid)
    if pending_employee_id is None or lowered not in _YES_WORDS:
        return None
    old_jid = await create_rebind_onboarding_service().existing_jid(pending_employee_id)
    if old_jid is None or old_jid == jid:
        return None
    # Intercept before cli._dm_onboarding calls bind(): no automatic takeover.
    await activation.clear_claim(jid)
    await rebind.stage(jid, pending_employee_id)
    return await _rebind_prompt(jid, pending_employee_id)


async def _route_operator(text: str, jid: str) -> str | None:
    workflow = create_workflow_control_service()
    operator = await workflow.resolve_jid(jid)
    if operator is not None:
        if not operator.active:
            return "Akses PMO WhatsApp untuk akun ini sudah dinonaktifkan. Hubungi admin."
        return await pmo_reply(operator, jid, text)

    token = text.strip()
    if not token.startswith("PMO-"):
        return None
    # A JID already bound as Talent can never turn itself into PMO by consuming
    # an invite; admin must first resolve that identity conflict deliberately.
    if await create_activation_service().resolve(jid) is not None:
        return "Nomor ini sudah terhubung sebagai Talent. PMO linking tidak dapat dilakukan di nomor ini."
    result = await workflow.consume_whatsapp_invite(jid, token)
    if result.outcome is InviteOutcome.LINKED and result.operator is not None:
        return await pmo_reply(result.operator, jid, "menu")
    if result.outcome is InviteOutcome.EXPIRED:
        return "Link aktivasi PMO sudah kedaluwarsa. Minta Admin membuat invite baru dari TalentOps."
    if result.outcome is InviteOutcome.USED:
        return "Link aktivasi PMO ini sudah pernah dipakai."
    if result.outcome is InviteOutcome.INACTIVE:
        return "Akun PMO untuk invite ini sudah tidak aktif."
    if result.outcome in (
        InviteOutcome.JID_ALREADY_LINKED,
        InviteOutcome.OPERATOR_ALREADY_LINKED,
    ):
        return "PMO WhatsApp sudah terhubung. Admin dapat unlink/reissue dari TalentOps jika perlu."
    return "Link aktivasi PMO tidak valid."


async def reply(text: str, jid: str) -> str:
    operator_reply = await _route_operator(text, jid)
    if operator_reply is not None:
        return operator_reply

    rebind_reply = await _handle_rebind_stage(text, jid)
    if rebind_reply is not None:
        return rebind_reply

    state = create_attendance_resolution_dm_state_service()
    draft = await state.pending(jid)
    if draft is None:
        activation = create_activation_service()
        employee_id = await activation.resolve(jid)
        lowered = text.strip().casefold()
        if employee_id is not None and lowered in _MENU_WORDS:
            return _talent_menu()
        if employee_id is not None and _wants_attendance_summary(text):
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
    workflow = create_workflow_control_service()
    operator = await workflow.resolve_jid(jid)
    if operator is not None:
        return "PMO DM tidak menerima upload evidence. Review evidence dilakukan dari queue / TalentOps Web."

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
    return _resolution_prompt(draft, legacy_reply)


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
