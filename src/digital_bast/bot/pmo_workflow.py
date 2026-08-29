"""PMO WhatsApp DM workflow over the same approval services used by Web.

No approval action is accepted in a group and no WhatsApp JID receives PMO
powers by itself. dm_workflow resolves a pre-provisioned WorkflowOperator first,
then delegates here. Button IDs and free-text commands converge on the same
service methods.
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING, Final
from uuid import UUID

from digital_bast.bot.attendance_resolution import (
    DecisionOutcome,
    ResolutionType,
)
from digital_bast.bot.interactive import interactive
from digital_bast.bot.rebind import RebindDecisionOutcome
from digital_bast.domain.completion import format_day
from digital_bast.operations import (
    create_attendance_resolution_service,
    create_identity_rebind_service,
    create_pmo_dm_state_service,
)

if TYPE_CHECKING:
    from digital_bast.application.workflow_control import WorkflowOperator
    from digital_bast.bot.attendance_resolution import AttendanceResolution
    from digital_bast.bot.rebind import RebindRequest

_MENU_WORDS: Final = frozenset({"menu", "halo", "hai", "hi", "start", "help", "bantuan"})
_CANCEL_WORDS: Final = frozenset({"batal", "cancel", "back", "kembali"})


def _time_label(value: time | None) -> str:
    return value.strftime("%H:%M") if value is not None else "-"


def _attendance_change(request: AttendanceResolution) -> str:
    if request.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return f"Clock In → {_time_label(request.proposed_check_in)}"
    if request.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return f"Clock Out → {_time_label(request.proposed_check_out)}"
    if request.resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return (
            f"Clock In {_time_label(request.proposed_check_in)} · "
            f"Clock Out {_time_label(request.proposed_check_out)}"
        )
    return request.absence_type.value.capitalize() if request.absence_type is not None else "Absen"


def _menu(operator: WorkflowOperator) -> str:
    actions: list[tuple[str, str]] = []
    if operator.can_approve_attendance:
        actions.append(("pmo:attendance", "Attendance"))
    if operator.can_approve_rebind:
        actions.append(("pmo:rebind", "Ganti Nomor"))
    actions.append(("pmo:menu", "Refresh"))
    return interactive(
        f"*PMO Digital BAST*\n{operator.display_name}\n\nPilih queue yang mau direview.",
        *actions,
        footer="Approval hanya berlaku di DM ini / TalentOps Web",
    )


def _find_by_prefix(items: tuple[AttendanceResolution, ...], prefix: str) -> AttendanceResolution | None:
    needle = prefix.strip().casefold()
    matches = tuple(item for item in items if str(item.id).casefold().startswith(needle))
    return matches[0] if len(matches) == 1 else None


def _find_rebind_by_prefix(items: tuple[RebindRequest, ...], prefix: str) -> RebindRequest | None:
    needle = prefix.strip().casefold()
    matches = tuple(item for item in items if str(item.id).casefold().startswith(needle))
    return matches[0] if len(matches) == 1 else None


async def _attendance_queue(operator: WorkflowOperator) -> str:
    if not operator.can_approve_attendance:
        return "Akun PMO ini tidak punya permission approval attendance."
    requests = await create_attendance_resolution_service().pending()
    if not requests:
        return interactive(
            "✅ Tidak ada attendance correction yang menunggu approval.",
            ("pmo:menu", "Menu PMO"),
        )
    lines = [f"*Pending Attendance* — {len(requests)} request", ""]
    for request in requests:
        lines.append(
            f"• `{str(request.id)[:8]}` · {request.full_name} ({request.nrp}) · "
            f"{format_day(request.work_date)} · {_attendance_change(request)}"
        )
    lines.extend(("", "Ketik `attendance <kode>` untuk buka detail."))
    return interactive("\n".join(lines), ("pmo:menu", "Menu PMO"))


async def _attendance_detail(operator: WorkflowOperator, prefix: str) -> str:
    if not operator.can_approve_attendance:
        return "Akun PMO ini tidak punya permission approval attendance."
    request = _find_by_prefix(await create_attendance_resolution_service().pending(), prefix)
    if request is None:
        return "Request attendance tidak ditemukan / kode ambigu. Buka queue lagi dengan `attendance`."
    text = (
        f"*Review Attendance*\n"
        f"{request.full_name} ({request.nrp})\n"
        f"Tanggal: {format_day(request.work_date)}\n"
        f"Pengajuan: {_attendance_change(request)}\n"
        f"Request: `{str(request.id)[:8]}`\n\n"
        "Raw Clock In/Out client tidak akan diubah. Approval hanya mengesahkan resolution/projection."
    )
    return interactive(
        text,
        (f"pmo:attendance:{request.id}:approve", "Approve"),
        (f"pmo:attendance:{request.id}:reject", "Reject"),
        ("pmo:attendance", "Kembali"),
    )


async def _approve_attendance(operator: WorkflowOperator, request_id: UUID) -> str:
    if not operator.can_approve_attendance:
        return "Akun PMO ini tidak punya permission approval attendance."
    result = await create_attendance_resolution_service().decide(
        request_id,
        operator.email,
        approve=True,
    )
    if result.outcome is DecisionOutcome.UPDATED:
        return interactive(
            "✅ Attendance resolution approved. Readiness akan memakai keputusan ini.",
            ("pmo:attendance", "Queue Attendance"),
            ("pmo:menu", "Menu PMO"),
        )
    if result.outcome is DecisionOutcome.ALREADY_RESOLVED:
        return "Request ini sudah diproses PMO lain. Kirim `attendance` untuk refresh queue."
    if result.outcome is DecisionOutcome.SOURCE_CHANGED:
        return "Data attendance client berubah. Request tidak di-approve; refresh queue dan review ulang."
    return "Request attendance tidak ditemukan atau tidak dapat diproses."


async def _reject_attendance_start(operator: WorkflowOperator, request_id: UUID, jid: str) -> str:
    if not operator.can_approve_attendance:
        return "Akun PMO ini tidak punya permission approval attendance."
    request = _find_by_prefix(await create_attendance_resolution_service().pending(), str(request_id))
    if request is None:
        return "Request ini sudah tidak pending. Kirim `attendance` untuk refresh queue."
    await create_pmo_dm_state_service().set(jid, "reject_attendance", request.id)
    return interactive(
        f"Kirim alasan reject untuk {request.full_name} — {format_day(request.work_date)}.",
        ("pmo:cancel", "Batal"),
    )


async def _rebind_queue(operator: WorkflowOperator) -> str:
    if not operator.can_approve_rebind:
        return "Akun PMO ini tidak punya permission approval ganti nomor."
    requests = await create_identity_rebind_service().pending(operator.scope_key)
    if not requests:
        return interactive(
            "✅ Tidak ada pengajuan ganti nomor yang menunggu approval.",
            ("pmo:menu", "Menu PMO"),
        )
    lines = [f"*Pending Ganti Nomor* — {len(requests)} request", ""]
    for request in requests:
        lines.append(
            f"• `{str(request.id)[:8]}` · {request.full_name} ({request.nrp}) · "
            f"{_mask_jid(request.old_wa_jid)} → {_mask_jid(request.new_wa_jid)}"
        )
    lines.extend(("", "Ketik `rebind <kode>` untuk buka detail."))
    return interactive("\n".join(lines), ("pmo:menu", "Menu PMO"))


def _mask_jid(jid: str) -> str:
    number = jid.split("@", 1)[0]
    if len(number) <= 6:
        return number
    return f"{number[:3]}***{number[-3:]}"


async def _rebind_detail(operator: WorkflowOperator, prefix: str) -> str:
    if not operator.can_approve_rebind:
        return "Akun PMO ini tidak punya permission approval ganti nomor."
    request = _find_rebind_by_prefix(
        await create_identity_rebind_service().pending(operator.scope_key), prefix
    )
    if request is None:
        return "Request rebind tidak ditemukan / kode ambigu. Buka queue lagi dengan `rebind`."
    text = (
        f"*Review Ganti Nomor*\n"
        f"{request.full_name} ({request.nrp})\n"
        f"Nomor lama: {_mask_jid(request.old_wa_jid)}\n"
        f"Nomor baru: {_mask_jid(request.new_wa_jid)}\n"
        f"Request: `{str(request.id)[:8]}`\n\n"
        "Nomor lama tetap aktif sampai approval berhasil."
    )
    return interactive(
        text,
        (f"pmo:rebind:{request.id}:approve", "Approve"),
        (f"pmo:rebind:{request.id}:reject", "Reject"),
        ("pmo:rebind", "Kembali"),
    )


async def _approve_rebind(operator: WorkflowOperator, request_id: UUID) -> str:
    if not operator.can_approve_rebind:
        return "Akun PMO ini tidak punya permission approval ganti nomor."
    result = await create_identity_rebind_service().decide(
        request_id,
        operator.email,
        approve=True,
    )
    if result.outcome is RebindDecisionOutcome.UPDATED:
        return interactive(
            "✅ Ganti nomor approved. Binding lama dicabut dan nomor baru sekarang aktif.",
            ("pmo:rebind", "Queue Ganti Nomor"),
            ("pmo:menu", "Menu PMO"),
        )
    if result.outcome is RebindDecisionOutcome.ALREADY_RESOLVED:
        return "Request ini sudah diproses PMO lain. Kirim `rebind` untuk refresh queue."
    if result.outcome is RebindDecisionOutcome.SOURCE_CHANGED:
        return "Binding lama sudah berubah. Approval dibatalkan; refresh dan review ulang."
    if result.outcome is RebindDecisionOutcome.NEW_NUMBER_ALREADY_BOUND:
        return "Nomor baru sudah terikat ke identity lain. Request tidak dapat di-approve."
    return "Request ganti nomor tidak ditemukan atau tidak dapat diproses."


async def _reject_rebind_start(operator: WorkflowOperator, request_id: UUID, jid: str) -> str:
    if not operator.can_approve_rebind:
        return "Akun PMO ini tidak punya permission approval ganti nomor."
    request = _find_rebind_by_prefix(
        await create_identity_rebind_service().pending(operator.scope_key), str(request_id)
    )
    if request is None:
        return "Request ini sudah tidak pending. Kirim `rebind` untuk refresh queue."
    await create_pmo_dm_state_service().set(jid, "reject_rebind", request.id)
    return interactive(
        f"Kirim alasan reject ganti nomor untuk {request.full_name}.",
        ("pmo:cancel", "Batal"),
    )


async def _finish_pending_rejection(operator: WorkflowOperator, jid: str, text: str) -> str | None:
    state = create_pmo_dm_state_service()
    pending = await state.get(jid)
    if pending is None:
        return None
    lowered = text.strip().casefold()
    if lowered in _CANCEL_WORDS or lowered == "pmo:cancel":
        await state.clear(jid)
        return _menu(operator)
    reason = text.strip()
    if not reason:
        return "Alasan reject wajib diisi. Kirim alasannya atau pilih Batal."
    if pending.action == "reject_attendance":
        if not operator.can_approve_attendance:
            await state.clear(jid)
            return "Permission approval attendance sudah dicabut."
        result = await create_attendance_resolution_service().decide(
            pending.request_id,
            operator.email,
            approve=False,
            rejection_reason=reason,
        )
        await state.clear(jid)
        if result.outcome is DecisionOutcome.UPDATED:
            return interactive(
                "❌ Attendance resolution rejected. Talent dapat melihat alasan dan mengajukan ulang.",
                ("pmo:attendance", "Queue Attendance"),
                ("pmo:menu", "Menu PMO"),
            )
        return "Request sudah berubah / diproses PMO lain. Queue perlu direfresh."
    if pending.action == "reject_rebind":
        if not operator.can_approve_rebind:
            await state.clear(jid)
            return "Permission approval ganti nomor sudah dicabut."
        result = await create_identity_rebind_service().decide(
            pending.request_id,
            operator.email,
            approve=False,
            rejection_reason=reason,
        )
        await state.clear(jid)
        if result.outcome is RebindDecisionOutcome.UPDATED:
            return interactive(
                "❌ Pengajuan ganti nomor rejected. Nomor lama tetap aktif.",
                ("pmo:rebind", "Queue Ganti Nomor"),
                ("pmo:menu", "Menu PMO"),
            )
        return "Request sudah berubah / diproses PMO lain. Queue perlu direfresh."
    await state.clear(jid)
    return _menu(operator)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


async def reply(operator: WorkflowOperator, jid: str, text: str) -> str:  # noqa: C901, PLR0911
    pending_reply = await _finish_pending_rejection(operator, jid, text)
    if pending_reply is not None:
        return pending_reply

    normalized = text.strip()
    lowered = normalized.casefold()
    if not normalized or lowered in _MENU_WORDS or lowered == "pmo:menu":
        return _menu(operator)
    if lowered in {"attendance", "approval attendance", "pmo:attendance"}:
        return await _attendance_queue(operator)
    if lowered in {"rebind", "ganti nomor", "approval nomor", "pmo:rebind"}:
        return await _rebind_queue(operator)

    parts = normalized.split(":")
    if len(parts) == 4 and parts[0] == "pmo" and parts[1] == "attendance":
        request_id = _uuid(parts[2])
        if request_id is None:
            return "Request ID attendance tidak valid."
        if parts[3] == "approve":
            return await _approve_attendance(operator, request_id)
        if parts[3] == "reject":
            return await _reject_attendance_start(operator, request_id, jid)
    if len(parts) == 4 and parts[0] == "pmo" and parts[1] == "rebind":
        request_id = _uuid(parts[2])
        if request_id is None:
            return "Request ID rebind tidak valid."
        if parts[3] == "approve":
            return await _approve_rebind(operator, request_id)
        if parts[3] == "reject":
            return await _reject_rebind_start(operator, request_id, jid)

    words = normalized.split(maxsplit=1)
    if len(words) == 2 and words[0].casefold() in {"attendance", "review"}:
        return await _attendance_detail(operator, words[1])
    if len(words) == 2 and words[0].casefold() in {"rebind", "nomor"}:
        return await _rebind_detail(operator, words[1])

    return _menu(operator)
