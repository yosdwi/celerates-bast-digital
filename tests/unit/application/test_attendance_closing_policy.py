from datetime import date, datetime, time, timedelta

import pytest

from digital_bast.application.attendance_closing_policy import (
    due_milestone,
    evaluated_through,
    payroll_cycle,
    payroll_cycle_for,
    reminder_milestones,
)
from digital_bast.domain.time import JAKARTA


def test_september_cycle_is_august_21_through_september_20() -> None:
    cycle = payroll_cycle(2026, 9)

    assert cycle.period.start == date(2026, 8, 21)
    assert cycle.period.end == date(2026, 9, 20)
    assert cycle.label == "Payroll September 2026"
    assert cycle.cycle_id == "2026-09:2026-08-21:2026-09-20"


def test_day_21_opens_next_payroll_cycle() -> None:
    cycle = payroll_cycle_for(date(2026, 9, 21))

    assert cycle.label_year == 2026
    assert cycle.label_month == 10
    assert cycle.period.start == date(2026, 9, 21)
    assert cycle.period.end == date(2026, 10, 20)


def test_january_cycle_crosses_year_boundary() -> None:
    cycle = payroll_cycle(2027, 1)

    assert cycle.period.start == date(2026, 12, 21)
    assert cycle.period.end == date(2027, 1, 20)


def test_large_closing_day_clamps_to_month_end() -> None:
    leap_cycle = payroll_cycle(2028, 2, closing_day=31)
    regular_cycle = payroll_cycle(2027, 2, closing_day=31)

    assert leap_cycle.period.start == date(2028, 2, 1)
    assert leap_cycle.period.end == date(2028, 2, 29)
    assert regular_cycle.period.start == date(2027, 2, 1)
    assert regular_cycle.period.end == date(2027, 2, 28)


def test_default_reminder_milestones_are_h5_h3_h1() -> None:
    cycle = payroll_cycle(2026, 9)

    milestones = reminder_milestones(cycle)

    assert [(item.label, item.work_date) for item in milestones] == [
        ("H-5", date(2026, 9, 15)),
        ("H-3", date(2026, 9, 17)),
        ("H-1", date(2026, 9, 19)),
    ]


def test_due_milestone_waits_until_reminder_hour() -> None:
    cycle = payroll_cycle(2026, 9)

    before = due_milestone(
        cycle,
        datetime(2026, 9, 15, 8, 59, tzinfo=JAKARTA),
        reminder_hour=9,
    )
    due = due_milestone(
        cycle,
        datetime(2026, 9, 15, 9, 0, tzinfo=JAKARTA),
        reminder_hour=9,
    )

    assert before is None
    assert due is not None
    assert due.label == "H-5"


def test_due_milestone_does_not_catch_up_on_later_date() -> None:
    cycle = payroll_cycle(2026, 9)

    assert (
        due_milestone(
            cycle,
            datetime(2026, 9, 16, 12, 0, tzinfo=JAKARTA),
            reminder_hour=9,
        )
        is None
    )


def test_evaluated_through_waits_for_shift_evaluation_boundary() -> None:
    cycle = payroll_cycle(2026, 9)

    def next_day_at_six(work_date: date) -> datetime:
        return datetime.combine(work_date + timedelta(days=1), time(6), JAKARTA)

    before_boundary = evaluated_through(
        cycle,
        datetime(2026, 9, 20, 5, 59, tzinfo=JAKARTA),
        next_day_at_six,
    )
    at_boundary = evaluated_through(
        cycle,
        datetime(2026, 9, 20, 6, 0, tzinfo=JAKARTA),
        next_day_at_six,
    )

    assert before_boundary == date(2026, 9, 18)
    assert at_boundary == date(2026, 9, 19)


def test_evaluated_through_never_passes_cycle_end() -> None:
    cycle = payroll_cycle(2026, 9)

    def same_day_midnight(work_date: date) -> datetime:
        return datetime.combine(work_date, time.min, JAKARTA)

    result = evaluated_through(
        cycle,
        datetime(2026, 9, 25, 12, 0, tzinfo=JAKARTA),
        same_day_midnight,
    )

    assert result == date(2026, 9, 20)


@pytest.mark.parametrize("closing_day", [0, 32])
def test_invalid_closing_day_is_rejected(closing_day: int) -> None:
    with pytest.raises(ValueError, match="closing_day"):
        payroll_cycle(2026, 9, closing_day=closing_day)


@pytest.mark.parametrize("reminder_hour", [-1, 24])
def test_invalid_reminder_hour_is_rejected(reminder_hour: int) -> None:
    with pytest.raises(ValueError, match="reminder_hour"):
        due_milestone(
            payroll_cycle(2026, 9),
            datetime(2026, 9, 15, 9, 0, tzinfo=JAKARTA),
            reminder_hour=reminder_hour,
        )
