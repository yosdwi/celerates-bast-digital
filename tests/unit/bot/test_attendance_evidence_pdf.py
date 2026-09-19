import pytest

from digital_bast.bot.attendance_evidence import (
    AttendanceEvidenceService,
    sniff_attendance_content_type,
)
from digital_bast.bot.evidence import MAX_IMAGE_BYTES, UploadOutcome, sniff_content_type


@pytest.mark.parametrize(
    ("payload", "content_type"),
    [
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"\xff\xd8\xffrest", "image/jpeg"),
        (b"RIFFxxxxWEBPrest", "image/webp"),
        (b"%PDF-1.7\nrest", "application/pdf"),
    ],
)
def test_attendance_sniffer_accepts_supported_signatures(
    payload: bytes,
    content_type: str,
) -> None:
    assert sniff_attendance_content_type(payload) == content_type


def test_pdf_filename_semantics_do_not_replace_signature_validation() -> None:
    assert sniff_attendance_content_type(b"not-a-real-pdf") is None


def test_task_evidence_sniffer_remains_image_only() -> None:
    assert sniff_content_type(b"%PDF-1.7\nrest") is None


def test_oversized_attendance_evidence_is_rejected_before_database_access() -> None:
    service = AttendanceEvidenceService("postgresql://unused")

    result = service._upload(
        "employee",
        "attendance-key",
        b"x" * (MAX_IMAGE_BYTES + 1),
        "",
    )

    assert result.outcome is UploadOutcome.TOO_LARGE


def test_fake_pdf_is_rejected_before_database_access() -> None:
    service = AttendanceEvidenceService("postgresql://unused")

    result = service._upload(
        "employee",
        "attendance-key",
        b"not-a-pdf",
        "",
    )

    assert result.outcome is UploadOutcome.UNSUPPORTED_TYPE
