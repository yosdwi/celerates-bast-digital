from datetime import date, time
from pathlib import Path

import pytest

from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.evidence import UploadOutcome, UploadResult
from digital_bast.bot.payroll_attendance_draft import PAYROLL_DRAFT_SUBMIT_ACTION_ID
from digital_bast.bot.payroll_attendance_evidence import attach_payroll_attendance_evidence

_JID = "628123@s.whatsapp.net"
_EMPLOYEE_ID = "MTG-TF/TEST1"
_ATTENDANCE_KEY = "ATT-2026-09-04"


def _draft(*, has_evidence: bool = False) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=_ATTENDANCE_KEY,
        employee_id=_EMPLOYEE_ID,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        work_date=date(2026, 9, 4),
        proposed_check_out=time(17, 40),
        has_evidence=has_evidence,
    )


class _Evidence:
    def __init__(self, outcome: UploadOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, bytes, str]] = []

    async def upload(
        self,
        employee_id: str,
        attendance_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        self.calls.append((employee_id, attendance_key, image, caption))
        return UploadResult(self.outcome)


class _State:
    def __init__(self, refreshed: AttendanceResolutionDraft | None) -> None:
        self.refreshed = refreshed
        self.calls: list[tuple[str, str, str]] = []
        self.cleared = False

    async def mark_evidence_ready(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft | None:
        self.calls.append((wa_jid, employee_id, attendance_key))
        return self.refreshed

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True


@pytest.mark.asyncio
async def test_image_is_attached_to_exact_active_draft_and_moves_to_review(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "bukti.jpg"
    file_path.write_bytes(b"\xff\xd8\xfftest-image")
    evidence = _Evidence(UploadOutcome.STORED)
    refreshed = _draft(has_evidence=True)
    state = _State(refreshed)

    response = await attach_payroll_attendance_evidence(
        jid=_JID,
        draft=_draft(),
        file_path=file_path,
        caption="bukti 4 sep",
        evidence=evidence,
        state=state,
    )

    assert evidence.calls == [
        (_EMPLOYEE_ID, _ATTENDANCE_KEY, b"\xff\xd8\xfftest-image", "bukti 4 sep")
    ]
    assert state.calls == [(_JID, _EMPLOYEE_ID, _ATTENDANCE_KEY)]
    assert state.cleared is False
    assert "Bukti attendance sudah tersimpan" in response
    assert "Clock Out: 17:40" in response
    assert "Bukti: ✓" in response
    assert "Ajukan informasi ini?" in response
    assert PAYROLL_DRAFT_SUBMIT_ACTION_ID in response


@pytest.mark.asyncio
async def test_pdf_payload_follows_same_active_draft_review_flow(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "bukti.pdf"
    file_path.write_bytes(b"%PDF-1.7\nattendance")
    evidence = _Evidence(UploadOutcome.STORED)
    state = _State(_draft(has_evidence=True))

    response = await attach_payroll_attendance_evidence(
        jid=_JID,
        draft=_draft(),
        file_path=file_path,
        caption="surat pendukung",
        evidence=evidence,
        state=state,
    )

    assert evidence.calls == [
        (_EMPLOYEE_ID, _ATTENDANCE_KEY, b"%PDF-1.7\nattendance", "surat pendukung")
    ]
    assert "Bukti attendance sudah tersimpan" in response
    assert "Bukti: ✓" in response
    assert "Ajukan informasi ini?" in response
    assert PAYROLL_DRAFT_SUBMIT_ACTION_ID in response


@pytest.mark.asyncio
async def test_duplicate_media_refreshes_existing_evidence_without_auto_submit(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "bukti.jpg"
    file_path.write_bytes(b"\xff\xd8\xffduplicate")
    state = _State(_draft(has_evidence=True))

    response = await attach_payroll_attendance_evidence(
        jid=_JID,
        draft=_draft(),
        file_path=file_path,
        caption="",
        evidence=_Evidence(UploadOutcome.DUPLICATE),
        state=state,
    )

    assert "sudah pernah tersimpan" in response
    assert "Bukti: ✓" in response
    assert "Ajukan informasi ini?" in response
    assert state.calls == [(_JID, _EMPLOYEE_ID, _ATTENDANCE_KEY)]
    assert state.cleared is False


@pytest.mark.asyncio
async def test_unsupported_media_does_not_mark_draft_evidence_ready(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "bukti.txt"
    file_path.write_bytes(b"not-supported")
    state = _State(_draft(has_evidence=True))

    response = await attach_payroll_attendance_evidence(
        jid=_JID,
        draft=_draft(),
        file_path=file_path,
        caption="",
        evidence=_Evidence(UploadOutcome.UNSUPPORTED_TYPE),
        state=state,
    )

    assert "belum didukung" in response
    assert "PNG, JPEG, WebP, atau PDF" in response
    assert state.calls == []
    assert state.cleared is False


@pytest.mark.asyncio
async def test_stored_evidence_with_changed_source_clears_only_stale_draft(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "bukti.jpg"
    file_path.write_bytes(b"\xff\xd8\xffsource-change")
    state = _State(None)

    response = await attach_payroll_attendance_evidence(
        jid=_JID,
        draft=_draft(),
        file_path=file_path,
        caption="",
        evidence=_Evidence(UploadOutcome.STORED),
        state=state,
    )

    assert state.cleared is True
    assert "Bukti sudah ada" in response
    assert "kondisi attendance berubah" in response
    assert "lengkapi" in response
