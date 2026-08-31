from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from digital_bast import cli
from digital_bast.bot.attendance_evidence import AttendanceEvidenceCandidate
from digital_bast.bot.evidence import EvidenceCandidate, UploadOutcome, UploadResult
from digital_bast.cli import (
    _NRP_ATTEMPT_MAX_ECHO,
    _NRP_HELP,
    _dm_onboarding,
    _nrp_not_found_reply,
    bot_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

_JID = "628123@s.whatsapp.net"
_EMPLOYEE_ID = "MTG-TF/TEST1"


def test_echoes_the_attempted_nrp_so_the_user_knows_what_was_read() -> None:
    reply = _nrp_not_found_reply("LJIMT24002")
    assert "LJIMT24002" in reply


def test_truncates_a_long_attempt_instead_of_echoing_it_verbatim() -> None:
    attempt = "x" * (_NRP_ATTEMPT_MAX_ECHO + 20)
    reply = _nrp_not_found_reply(attempt)
    assert attempt not in reply
    assert "x" * _NRP_ATTEMPT_MAX_ECHO in reply


class _FakeActivationService:
    async def pending_claim(self, wa_jid: str) -> None:
        assert wa_jid == _JID


@pytest.mark.asyncio
async def test_onboarding_greets_a_not_yet_bound_sender_instead_of_erroring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "halo" from someone we don't know yet used to fall straight into NRP
    # lookup and come back as "NRP 'halo' belum aku kenali" -- a genuine
    # greeting shouldn't read as a rejected ID. It gets the same friendly
    # nudge a blank message already got.
    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationService)
    for greeting in ("halo", "Hai", "MENU", "  "):
        assert await _dm_onboarding(greeting, _JID) == _NRP_HELP


@pytest.mark.asyncio
async def test_onboarding_still_rejects_a_genuinely_unrecognized_nrp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression guard: only greetings/blank get the friendly nudge --
    # a real, wrong-looking NRP attempt must still get the not-found error
    # (with the attempt echoed back) so the sender knows what was read.
    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationService)

    async def empty_roster() -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(cli, "load_roster", empty_roster)
    reply = await _dm_onboarding("LJIMT99999", _JID)
    assert "LJIMT99999" in reply
    assert reply != _NRP_HELP


class _FakeActivationResolved:
    async def resolve(self, wa_jid: str) -> str:
        assert wa_jid == _JID
        return _EMPLOYEE_ID


class _FakeAttendanceNoPending:
    def __init__(self) -> None:
        self.uploaded: tuple[str, str, bytes, str] | None = None
        self.cleared = False
        self.mark_active_called = False

    async def pending_attendance(self, wa_jid: str) -> None:
        assert wa_jid == _JID

    async def upload(
        self, employee_id: str, attendance_key: str, image: bytes, caption: str
    ) -> UploadResult:
        self.uploaded = (employee_id, attendance_key, image, caption)
        return UploadResult(UploadOutcome.STORED)

    async def clear_pending_attendance(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True

    async def mark_active(self, wa_jid: str) -> None:
        self.mark_active_called = True


class _FakeEvidenceAttendanceActive:
    """active_kind() says the attendance list was just shown -- the Closed-task
    pool must never be consulted from here (see bot_evidence's fix)."""

    async def active_kind(self, wa_jid: str) -> str:
        assert wa_jid == _JID
        return "attendance"

    async def list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        message = "must not fall through to the Closed-task pool"
        raise AssertionError(message)

    async def stash_image(
        self, wa_jid: str, image: bytes, content_type: str, caption: str
    ) -> None:
        message = "a matched index must upload directly, not stash"
        raise AssertionError(message)


@pytest.mark.asyncio
async def test_attendance_photo_with_index_caption_uploads_without_a_separate_pick(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for a real production bug: a talent attaches the evidence
    # photo and types the day number as that photo's OWN caption (one
    # WhatsApp message) instead of sending "1" as a separate text reply
    # first. Before this fix, bot_evidence only recognized a pick made via a
    # prior separate text message (pending_attendance_id) -- this caption-only
    # pick fell straight through to the Closed-task pool, matched nothing,
    # and replied with the wrong list ("Closed task tanpa evidence") for a
    # photo that was never about a task at all.
    candidate = AttendanceEvidenceCandidate(
        "ATT-1", date(2026, 8, 5), "Attendance 5 Agustus 2026", 0
    )
    attendance = _FakeAttendanceNoPending()
    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationResolved)
    monkeypatch.setattr(cli, "create_evidence_service", _FakeEvidenceAttendanceActive)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", lambda: attendance)

    async def fake_candidates(
        employee_id: str, attendance_service: object, today: date
    ) -> tuple[AttendanceEvidenceCandidate, ...]:
        assert employee_id == _EMPLOYEE_ID
        assert attendance_service is attendance
        return (candidate,)

    monkeypatch.setattr(cli, "_attendance_evidence_candidates", fake_candidates)

    file_path = tmp_path / "evidence.jpg"
    file_path.write_bytes(b"fake-image-bytes")

    reply = await bot_evidence(_JID, file_path, "1. 5 Agustus 2026")

    assert attendance.uploaded == (_EMPLOYEE_ID, "ATT-1", b"fake-image-bytes", "1. 5 Agustus 2026")
    assert attendance.cleared is True
    assert attendance.mark_active_called is False
    assert "tersimpan" in reply.casefold()


@pytest.mark.asyncio
async def test_attendance_photo_with_unmatched_caption_is_stashed_not_misfiled_as_a_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Same setup, but the caption has no day number at all -- must ask for
    # the right number (and keep the photo) instead of silently matching it
    # against Closed task titles.
    candidate = AttendanceEvidenceCandidate(
        "ATT-1", date(2026, 8, 5), "Attendance 5 Agustus 2026", 0
    )
    attendance = _FakeAttendanceNoPending()

    class _EvidenceStashes(_FakeEvidenceAttendanceActive):
        def __init__(self) -> None:
            self.stashed: tuple[str, bytes, str, str] | None = None

        async def stash_image(
            self, wa_jid: str, image: bytes, content_type: str, caption: str
        ) -> None:
            self.stashed = (wa_jid, image, content_type, caption)

    evidence = _EvidenceStashes()
    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationResolved)
    monkeypatch.setattr(cli, "create_evidence_service", lambda: evidence)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", lambda: attendance)

    async def fake_candidates(
        employee_id: str, attendance_service: object, today: date
    ) -> tuple[AttendanceEvidenceCandidate, ...]:
        return (candidate,)

    monkeypatch.setattr(cli, "_attendance_evidence_candidates", fake_candidates)

    file_path = tmp_path / "evidence.jpg"
    file_path.write_bytes(b"fake-image-bytes")

    reply = await bot_evidence(_JID, file_path, "surat sakit dokter")

    assert attendance.uploaded is None
    assert evidence.stashed == (_JID, b"fake-image-bytes", "image/jpeg", "surat sakit dokter")
    assert attendance.mark_active_called is True
    assert reply == cli._ATTENDANCE_HELP_REPLY


@pytest.mark.asyncio
async def test_task_evidence_unaffected_when_no_attendance_context_is_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression guard for the fix above: when the attendance list was never
    # the last thing shown, a photo+caption must still resolve against the
    # Closed-task pool exactly as before.
    task_candidate = EvidenceCandidate("redmine", "T-1", "Monitoring CCTV", date(2026, 8, 1), 0)

    class _EvidenceNoAttendanceContext:
        async def active_kind(self, wa_jid: str) -> None:
            return None

        async def list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
            assert employee_id == _EMPLOYEE_ID
            return (task_candidate,)

    class _AttendanceNotConsulted:
        async def pending_attendance(self, wa_jid: str) -> None:
            assert wa_jid == _JID

    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationResolved)
    monkeypatch.setattr(cli, "create_evidence_service", _EvidenceNoAttendanceContext)
    monkeypatch.setattr(cli, "create_attendance_evidence_service", _AttendanceNotConsulted)

    async def fake_complete_upload(  # noqa: PLR0913, PLR0917 -- mirrors _complete_upload's own signature
        evidence: object,
        employee_id: str,
        jid: str,
        target: EvidenceCandidate,
        image: bytes,
        caption: str,
    ) -> str:
        return f"uploaded-task:{target.task_key}"

    monkeypatch.setattr(cli, "_complete_upload", fake_complete_upload)

    file_path = tmp_path / "evidence.jpg"
    file_path.write_bytes(b"fake-image-bytes")

    reply = await bot_evidence(_JID, file_path, "1")

    assert reply == "uploaded-task:T-1"
