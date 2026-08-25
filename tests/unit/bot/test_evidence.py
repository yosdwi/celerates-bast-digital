from __future__ import annotations

from datetime import date

from digital_bast.bot.attendance_evidence import AttendanceEvidenceCandidate
from digital_bast.bot.evidence import (
    EvidenceCandidate,
    select_by_caption,
    select_by_caption_all,
    select_by_index,
)

DAY = date(2026, 8, 1)
CANDIDATES = (
    EvidenceCandidate("redmine", "1", "Monitoring CCTV", DAY, 0),
    EvidenceCandidate("redmine", "2", "Monitoring Device Health", DAY, 0),
    EvidenceCandidate("redmine", "3", "MIR Perimeter Sync", DAY, 0),
)


def test_select_by_index_is_one_based_and_bounded() -> None:
    first = select_by_index(CANDIDATES, "1")
    third = select_by_index(CANDIDATES, "3")
    assert first is not None
    assert third is not None
    assert first.title == "Monitoring CCTV"
    assert third.title == "MIR Perimeter Sync"
    assert select_by_index(CANDIDATES, "0") is None
    assert select_by_index(CANDIDATES, "4") is None
    assert select_by_index(CANDIDATES, "abc") is None


def test_select_by_caption_all_returns_every_bounded_match() -> None:
    # Two of the three candidates' titles contain "monitoring" -- both must
    # be returned so the caller can ask a clarifying question (§5), never
    # silently guessing one.
    matches = select_by_caption_all(CANDIDATES, "ini buat monitoring")
    assert {c.title for c in matches} == {"Monitoring CCTV", "Monitoring Device Health"}


def test_select_by_caption_resolves_only_when_unambiguous() -> None:
    resolved = select_by_caption(CANDIDATES, "ini buat CCTV Gate")
    assert resolved is not None
    assert resolved.title == "Monitoring CCTV"
    assert select_by_caption(CANDIDATES, "ini buat monitoring") is None
    assert select_by_caption(CANDIDATES, "ini buat sesuatu yang tidak ada") is None


def test_selection_helpers_also_work_on_attendance_candidates() -> None:
    # select_by_index/select_by_caption_all are shared between the Task List
    # and Attendance DM flows via a structural `title` Protocol, not
    # inheritance -- this locks in that AttendanceEvidenceCandidate keeps
    # satisfying it. Distinct words on purpose, not real format_day() output
    # -- a bare day number ("1" vs "2") is too short to survive
    # _MIN_KEYWORD_LENGTH, so real attendance titles in the same month can't
    # be told apart by caption alone; index-based selection is the supported
    # path for that (see cli.py's attendance DM flow), this only proves reuse.
    candidates = (
        AttendanceEvidenceCandidate("1", DAY, "Attendance Senin", 0),
        AttendanceEvidenceCandidate("2", DAY, "Attendance Selasa", 0),
    )
    by_index = select_by_index(candidates, "2")
    assert by_index is not None
    assert by_index.title == "Attendance Selasa"
    by_caption = select_by_caption_all(candidates, "yang hari senin")
    assert {c.title for c in by_caption} == {"Attendance Senin"}
