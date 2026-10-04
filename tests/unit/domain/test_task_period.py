from __future__ import annotations

from datetime import date

import pytest

from digital_bast.bot.task_evidence_submission import TaskEvidenceCandidate
from digital_bast.domain.completion import DateRange
from digital_bast.domain.models import reported_in_period

SEPTEMBER = DateRange(date(2026, 9, 1), date(2026, 9, 30))


@pytest.mark.parametrize(
    ("end_date", "expected"),
    [
        (date(2026, 9, 1), True),  # first day is inside
        (date(2026, 9, 30), True),  # last day is inside
        (date(2026, 9, 15), True),
        (date(2026, 8, 31), False),  # ended the day before
        (date(2026, 10, 1), False),  # ended the day after
        (None, False),  # no end date yet: in no period
    ],
)
def test_a_task_belongs_to_the_period_it_ends_in(end_date: date | None, expected: bool) -> None:
    assert reported_in_period(end_date, SEPTEMBER.start, SEPTEMBER.end) is expected


def _candidate(work_date: date, end_date: date | None) -> TaskEvidenceCandidate:
    return TaskEvidenceCandidate(
        "redmine", "k", "Task", work_date, 0, 0, "Closed", closed=True, end_date=end_date
    )


def test_started_in_august_ended_in_september_is_a_september_task() -> None:
    assert _candidate(date(2026, 8, 28), date(2026, 9, 3)).in_period(SEPTEMBER)


def test_started_in_september_ended_in_october_is_not_a_september_task() -> None:
    assert not _candidate(date(2026, 9, 29), date(2026, 10, 7)).in_period(SEPTEMBER)


def test_a_task_without_an_end_date_is_never_listed() -> None:
    assert not _candidate(date(2026, 9, 10), None).in_period(SEPTEMBER)


def test_positional_construction_without_an_end_date_still_works() -> None:
    legacy = TaskEvidenceCandidate(
        "redmine", "k", "Task", date(2026, 9, 10), 0, 0, "Closed", closed=True
    )
    assert legacy.end_date is None
    assert not legacy.in_period(SEPTEMBER)
