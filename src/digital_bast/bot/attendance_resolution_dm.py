"""Deterministic WhatsApp-DM parsing for attendance correction proposals.

This module deliberately does not read or mutate database state. It converts a
small, explicit set of talent replies into ordered resolution proposals. The
caller still asks AttendanceResolutionService to validate each proposal against
the immutable client attendance row, so a text parser can never decide which
clock field is actually missing on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from typing import Final

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType

_CLOCK_RE: Final = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)")
_MAX_CLOCK_VALUES: Final = 2
_ABSENCE_WORDS: Final = {
    "cuti": AbsenceType.CUTI,
    "izin": AbsenceType.IZIN,
    "ijin": AbsenceType.IZIN,
    "sakit": AbsenceType.SAKIT,
}
_WORK_WORDS: Final = ("kerja", "masuk", "hadir", "bekerja")


@dataclass(frozen=True, slots=True)
class ResolutionProposal:
    resolution_type: ResolutionType
    proposed_check_in: time | None = None
    proposed_check_out: time | None = None
    absence_type: AbsenceType | None = None


def parse_clock_times(text: str) -> tuple[time, ...]:
    """Return at most two clock values, preserving user order.

    Both ``07:30`` and the common WhatsApp shorthand ``07.30`` are accepted.
    More than two clock values is treated as ambiguous by ``proposals`` rather
    than guessing which pair the talent intended.
    """
    return tuple(
        time(int(match.group(1)), int(match.group(2)))
        for match in _CLOCK_RE.finditer(text)
    )


def _absence_type(text: str) -> AbsenceType | None:
    lowered = text.casefold()
    return next((kind for word, kind in _ABSENCE_WORDS.items() if word in lowered), None)


def looks_like_resolution_input(text: str) -> bool:
    lowered = text.casefold()
    return bool(
        _CLOCK_RE.search(text)
        or _absence_type(text) is not None
        or any(word in lowered for word in _WORK_WORDS)
    )


def proposals(text: str) -> tuple[ResolutionProposal, ...]:
    """Build ordered proposals without assuming which source punch is missing.

    The order is intentional:
    * two times: try a both-missing worked day, then fall back to the first
      value as Clock In or the last value as Clock Out;
    * one time: try Clock In then Clock Out;
    * an absence word: propose absence only.

    AttendanceResolutionService remains the authority that rejects proposal
    shapes inconsistent with the actual source row. Mixed absence + clock text
    and messages containing more than two times are rejected as ambiguous.
    """
    times = parse_clock_times(text)
    absence = _absence_type(text)
    if absence is not None:
        if times:
            return ()
        return (ResolutionProposal(ResolutionType.ABSENCE, absence_type=absence),)
    if len(times) > _MAX_CLOCK_VALUES:
        return ()
    if len(times) == _MAX_CLOCK_VALUES:
        check_in, check_out = times
        return (
            ResolutionProposal(
                ResolutionType.MISSING_BOTH_WORKED,
                proposed_check_in=check_in,
                proposed_check_out=check_out,
            ),
            ResolutionProposal(ResolutionType.MISSING_CLOCK_IN, proposed_check_in=check_in),
            ResolutionProposal(ResolutionType.MISSING_CLOCK_OUT, proposed_check_out=check_out),
        )
    if len(times) == 1:
        value = times[0]
        return (
            ResolutionProposal(ResolutionType.MISSING_CLOCK_IN, proposed_check_in=value),
            ResolutionProposal(ResolutionType.MISSING_CLOCK_OUT, proposed_check_out=value),
        )
    return ()
