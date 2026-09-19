"""Attach media evidence to the exact active Payroll attendance draft.

P11 deliberately bypasses legacy candidate selection once a stable Payroll draft
is active: the draft already carries the canonical attendance identity and owner.
This module stores image evidence, refreshes the durable draft, and never submits
a PMO request. PDF support is intentionally deferred to P12.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from anyio.to_thread import run_sync

from digital_bast.bot.evidence import UploadOutcome
from digital_bast.bot.payroll_attendance_draft import render_payroll_draft_prompt

if TYPE_CHECKING:
    from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
    from digital_bast.bot.evidence import UploadResult


class AttendanceEvidenceWriter(Protocol):
    async def upload(
        self,
        employee_id: str,
        attendance_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult: ...


class AttendanceDraftEvidenceState(Protocol):
    async def mark_evidence_ready(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft | None: ...


_OUTCOME_REPLY = {
    UploadOutcome.NOT_FOUND: "Attendance ini sudah tidak ditemukan.",
    UploadOutcome.NOT_OWNED: "Attendance ini bukan milik kamu.",
    UploadOutcome.TOO_LARGE: "Ukuran file lebih dari 5 MB.",
    UploadOutcome.UNSUPPORTED_TYPE: (
        "Format file belum didukung. Kirim PNG, JPEG, atau WebP."
    ),
}


async def attach_payroll_attendance_evidence(
    *,
    jid: str,
    draft: AttendanceResolutionDraft,
    file_path: Path,
    caption: str,
    evidence: AttendanceEvidenceWriter,
    state: AttendanceDraftEvidenceState,
) -> str:
    """Store media for the exact draft identity and preserve proposed values."""
    payload = await run_sync(file_path.read_bytes)
    result = await evidence.upload(
        draft.employee_id,
        draft.attendance_key,
        payload,
        caption,
    )
    if result.outcome not in {UploadOutcome.STORED, UploadOutcome.DUPLICATE}:
        return _OUTCOME_REPLY.get(result.outcome, "Bukti belum bisa disimpan. Coba lagi.")

    refreshed = await state.mark_evidence_ready(
        jid,
        draft.employee_id,
        draft.attendance_key,
    )
    if refreshed is None:
        return (
            "Bukti sudah ada, tapi kondisi attendance berubah sebelum draft diperbarui. "
            "Balas `lengkapi` lagi untuk memuat kondisi terbaru."
        )

    prefix = (
        "Bukti attendance sudah tersimpan."
        if result.outcome is UploadOutcome.STORED
        else "Bukti ini sudah pernah tersimpan."
    )
    return render_payroll_draft_prompt(refreshed, prefix=prefix)
