"""Shared attendance-gap resolution form helpers.

Used by both the talent-facing mobile flow (talent_mobile_router.py, token
auth) and the PMO-facing bulk gap page (talentops_router.py, session auth) --
factored out so the parsing/validation rules live in exactly one place.
"""

from __future__ import annotations

from datetime import time
from typing import Literal

from fastapi import HTTPException, UploadFile, status

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.bot.evidence import MAX_IMAGE_BYTES

type AttendanceGap = Literal["missing_clock_in", "missing_clock_out", "missing_both"]


def clock_label(value: time | None) -> str | None:
    return None if value is None else value.strftime("%H:%M")


def gap_for(check_in: time | None, check_out: time | None) -> AttendanceGap:
    if check_in is None and check_out is None:
        return "missing_both"
    return "missing_clock_in" if check_in is None else "missing_clock_out"


def request_label(resolution_type: ResolutionType, absence_type: AbsenceType | None) -> str:
    if resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return "Koreksi Clock In"
    if resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return "Koreksi Clock Out"
    if resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return "Saya bekerja"
    return absence_type.value.capitalize() if absence_type is not None else "Attendance"


def parse_clock(value: str | None, label: str) -> time | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} tidak valid",
        ) from error
    return parsed.replace(second=0, microsecond=0)


def resolution_shape(
    gap: AttendanceGap,
    action: str,
    check_in_text: str | None,
    check_out_text: str | None,
) -> tuple[ResolutionType, time | None, time | None, AbsenceType | None]:
    normalized = action.strip().casefold()
    check_in = parse_clock(check_in_text, "Jam masuk")
    check_out = parse_clock(check_out_text, "Jam pulang")
    if gap == "missing_clock_in":
        if normalized != "worked" or check_in is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Isi jam masuk yang benar untuk melanjutkan",
            )
        return ResolutionType.MISSING_CLOCK_IN, check_in, None, None
    if gap == "missing_clock_out":
        if normalized != "worked" or check_out is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Isi jam pulang yang benar untuk melanjutkan",
            )
        return ResolutionType.MISSING_CLOCK_OUT, None, check_out, None
    if normalized == "worked":
        if check_in is None or check_out is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Isi jam masuk dan jam pulang untuk melanjutkan",
            )
        return ResolutionType.MISSING_BOTH_WORKED, check_in, check_out, None
    try:
        absence = AbsenceType(normalized)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pilih Saya bekerja, Sakit, Izin, atau Cuti",
        ) from error
    # Clock in/out are optional (not mandatory) for an absence day -- a
    # talent on Cuti/Izin/Sakit may still have punched in/out partially.
    return ResolutionType.ABSENCE, check_in, check_out, absence


async def read_upload(upload: UploadFile) -> bytes:
    try:
        content = await upload.read(MAX_IMAGE_BYTES + 1)
    finally:
        await upload.close()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Ukuran evidence maksimal 5 MB",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File evidence kosong")
    return content
