from __future__ import annotations

from datetime import date

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
