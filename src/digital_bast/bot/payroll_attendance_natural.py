"""Natural-language candidate extraction for an already-selected Payroll gap.

This module never selects a Talent, attendance row, or approval outcome and never
writes state. The caller owns the active durable draft and must revalidate it
before saving any candidate returned here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ValidationError, field_validator

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.bot.attendance_resolution_dm import ResolutionProposal
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from digital_bast.application.talentops_ai import TalentOpsChatClient

_MONTHS: Final = {
    "januari": 1,
    "jan": 1,
    "februari": 2,
    "feb": 2,
    "maret": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "mei": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "agustus": 8,
    "agu": 8,
    "agt": 8,
    "september": 9,
    "sep": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "desember": 12,
    "des": 12,
}
_MONTH_PATTERN: Final = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO_DATE_RE: Final = re.compile(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
_DMY_DATE_RE: Final = re.compile(
    r"(?<![\d-])([0-3]?\d)[/-]([01]?\d)(?:[/-](20\d{2}))?(?!\d)"
)
_MONTH_DATE_RE: Final = re.compile(
    rf"(?<!\d)([0-3]?\d)\s+({_MONTH_PATTERN})(?:\s+(20\d{{2}}))?(?!\d)",
    re.IGNORECASE,
)
_DAY_ONLY_RE: Final = re.compile(r"\b(?:tanggal|tgl)\s+([0-3]?\d)\b", re.IGNORECASE)
_NATURAL_HINTS: Final = (
    "jam",
    "clock",
    "masuk",
    "pulang",
    "keluar",
    "kemarin",
    "hari ini",
    "tanggal",
    "tgl",
    "cuti",
    "izin",
    "ijin",
    "sakit",
    "libur",
    "hadir",
    "kerja",
)

_SYSTEM_PROMPT: Final = (
    "Kamu mengekstrak kandidat koreksi attendance dari SATU pesan Talent. "
    "Kamu bukan penentu attendance yang benar, bukan penentu gap aktif, dan tidak boleh "
    "menganggap sebuah nilai sudah disetujui. Balas HANYA JSON valid dengan skema:\n"
    '{"work_date":"YYYY-MM-DD atau null",'
    '"resolution_type":"missing_clock_in|missing_clock_out|missing_both_worked|absence|unknown",'
    '"check_in":"HH:MM atau null","check_out":"HH:MM atau null",'
    '"absence_type":"cuti|izin|sakit|libur|null"}\n'
    "Gunakan timestamp pesan untuk kata relatif seperti kemarin/hari ini. Jika user tidak "
    "menyebut tanggal sama sekali, work_date=null. Jangan salin tanggal gap aktif ke work_date "
    "hanya karena tanggal itu diberikan sebagai konteks. Untuk missing_clock_in isi check_in "
    "saja; missing_clock_out isi check_out saja; missing_both_worked wajib dua jam yang jelas; "
    "absence wajib absence_type dan tanpa jam. Jika kalimat ambigu, hanya menyatakan bekerja, "
    "atau tidak memberi nilai waktu/status yang cukup, gunakan unknown. Jangan menebak jam."
)


@dataclass(frozen=True, slots=True)
class ExplicitWorkDate:
    mentioned: bool
    work_date: date | None


@dataclass(frozen=True, slots=True)
class PayrollAttendanceCandidate:
    work_date: date | None
    resolution_type: ResolutionType
    proposed_check_in: time | None = None
    proposed_check_out: time | None = None
    absence_type: AbsenceType | None = None


class _NaturalDraft(BaseModel):
    work_date: date | None = None
    resolution_type: Literal[
        "missing_clock_in",
        "missing_clock_out",
        "missing_both_worked",
        "absence",
        "unknown",
    ]
    check_in: time | None = None
    check_out: time | None = None
    absence_type: Literal["cuti", "izin", "sakit", "libur"] | None = None

    @field_validator("work_date", "check_in", "check_out", "absence_type", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().casefold() in {"", "null", "none"}:
            return None
        return value


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _message_local_date(message_at: datetime) -> date:
    if message_at.tzinfo is None:
        raise ValueError("message_at must be timezone-aware")
    return message_at.astimezone(JAKARTA).date()


def explicit_work_date(
    text: str,
    *,
    message_at: datetime,
    active_work_date: date,
) -> ExplicitWorkDate:
    """Extract only explicit/relative dates without selecting a different gap.

    Day-only phrases such as ``tanggal 7`` are interpreted in the active gap's
    month/year solely for comparison with that already-selected gap. They never
    cause navigation to another attendance row.
    """

    lowered = text.casefold()
    message_date = _message_local_date(message_at)
    candidates: list[date | None] = []

    if re.search(r"\bkemarin\b", lowered):
        candidates.append(message_date - timedelta(days=1))
    if re.search(r"\b(?:hari\s+ini|today)\b", lowered):
        candidates.append(message_date)

    for match in _ISO_DATE_RE.finditer(text):
        candidates.append(_safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3))))

    for match in _DMY_DATE_RE.finditer(text):
        year = int(match.group(3)) if match.group(3) else message_date.year
        candidates.append(_safe_date(year, int(match.group(2)), int(match.group(1))))

    for match in _MONTH_DATE_RE.finditer(text):
        year = int(match.group(3)) if match.group(3) else message_date.year
        month = _MONTHS[match.group(2).casefold()]
        candidates.append(_safe_date(year, month, int(match.group(1))))

    for match in _DAY_ONLY_RE.finditer(text):
        candidates.append(
            _safe_date(active_work_date.year, active_work_date.month, int(match.group(1)))
        )

    if not candidates:
        return ExplicitWorkDate(False, None)
    unique = {item for item in candidates if item is not None}
    if len(unique) != 1 or any(item is None for item in candidates):
        return ExplicitWorkDate(True, None)
    return ExplicitWorkDate(True, next(iter(unique)))


def looks_like_natural_attendance_input(text: str) -> bool:
    lowered = text.casefold()
    return any(hint in lowered for hint in _NATURAL_HINTS)


def _candidate_from_draft(draft: _NaturalDraft) -> PayrollAttendanceCandidate | None:
    if draft.resolution_type == "unknown":
        return None
    resolution_type = ResolutionType(draft.resolution_type)
    absence = AbsenceType(draft.absence_type) if draft.absence_type is not None else None

    valid = False
    if resolution_type is ResolutionType.MISSING_CLOCK_IN:
        valid = draft.check_in is not None and draft.check_out is None and absence is None
    elif resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        valid = draft.check_out is not None and draft.check_in is None and absence is None
    elif resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        valid = draft.check_in is not None and draft.check_out is not None and absence is None
    elif resolution_type is ResolutionType.ABSENCE:
        valid = absence is not None and draft.check_in is None and draft.check_out is None
    if not valid:
        return None

    return PayrollAttendanceCandidate(
        work_date=draft.work_date,
        resolution_type=resolution_type,
        proposed_check_in=draft.check_in,
        proposed_check_out=draft.check_out,
        absence_type=absence,
    )


def proposal_for_active_gap(
    candidate: PayrollAttendanceCandidate,
    *,
    active_work_date: date,
    active_resolution_type: ResolutionType,
) -> ResolutionProposal | None:
    """Fail closed unless the candidate can satisfy exactly the active draft."""

    if candidate.work_date is not None and candidate.work_date != active_work_date:
        return None
    if active_resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        if candidate.resolution_type not in {
            ResolutionType.MISSING_BOTH_WORKED,
            ResolutionType.ABSENCE,
        }:
            return None
    elif candidate.resolution_type is not active_resolution_type:
        return None
    return ResolutionProposal(
        candidate.resolution_type,
        proposed_check_in=candidate.proposed_check_in,
        proposed_check_out=candidate.proposed_check_out,
        absence_type=candidate.absence_type,
    )


class PayrollAttendanceNaturalInterpreter:
    def __init__(self, client: TalentOpsChatClient) -> None:
        self._client = client

    async def interpret(
        self,
        text: str,
        *,
        message_at: datetime,
        active_work_date: date,
        active_resolution_type: ResolutionType,
    ) -> PayrollAttendanceCandidate | None:
        local = message_at.astimezone(JAKARTA)
        user_prompt = (
            f"Message timestamp Asia/Jakarta: {local.isoformat()}\n"
            f"Current active gap date (context only): {active_work_date.isoformat()}\n"
            f"Current active gap type (context only): {active_resolution_type.value}\n"
            f"Pesan Talent: {text}"
        )
        content = await self._client.complete(_SYSTEM_PROMPT, user_prompt)
        if content is None:
            return None
        try:
            draft = _NaturalDraft.model_validate_json(content)
        except ValidationError:
            return None
        return _candidate_from_draft(draft)
