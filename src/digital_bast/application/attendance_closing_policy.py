from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from digital_bast.domain.completion import MONTH_NAMES, DateRange
from digital_bast.domain.time import in_jakarta

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class PayrollCycle:
    label_year: int
    label_month: int
    closing_day: int
    period: DateRange

    @property
    def cycle_id(self) -> str:
        return (
            f"{self.label_year:04d}-{self.label_month:02d}:"
            f"{self.period.start.isoformat()}:{self.period.end.isoformat()}"
        )

    @property
    def label(self) -> str:
        return f"Payroll {MONTH_NAMES[self.label_month - 1]} {self.label_year}"


@dataclass(frozen=True, slots=True)
class PayrollReminderMilestone:
    days_before: int
    work_date: date

    @property
    def label(self) -> str:
        return f"H-{self.days_before}"


def _validate_closing_day(closing_day: int) -> None:
    if not 1 <= closing_day <= 31:
        msg = "closing_day must be between 1 and 31"
        raise ValueError(msg)


def _validate_reminder_hour(reminder_hour: int) -> None:
    if not 0 <= reminder_hour <= 23:
        msg = "reminder_hour must be between 0 and 23"
        raise ValueError(msg)


def _clamped_date(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def payroll_cycle(label_year: int, label_month: int, closing_day: int = 20) -> PayrollCycle:
    _validate_closing_day(closing_day)
    end = _clamped_date(label_year, label_month, closing_day)
    previous_year, previous_month = _previous_month(label_year, label_month)
    previous_cutoff = _clamped_date(previous_year, previous_month, closing_day)
    return PayrollCycle(
        label_year=label_year,
        label_month=label_month,
        closing_day=closing_day,
        period=DateRange(previous_cutoff + timedelta(days=1), end),
    )


def payroll_cycle_for(work_date: date, closing_day: int = 20) -> PayrollCycle:
    current = payroll_cycle(work_date.year, work_date.month, closing_day)
    if work_date <= current.period.end:
        return current
    next_year, next_month = _next_month(work_date.year, work_date.month)
    return payroll_cycle(next_year, next_month, closing_day)


def reminder_milestones(
    cycle: PayrollCycle,
    offsets: tuple[int, ...] = (5, 3, 1),
) -> tuple[PayrollReminderMilestone, ...]:
    normalized = tuple(sorted({offset for offset in offsets if offset > 0}, reverse=True))
    return tuple(
        PayrollReminderMilestone(
            days_before=offset,
            work_date=cycle.period.end - timedelta(days=offset),
        )
        for offset in normalized
    )


def due_milestone(
    cycle: PayrollCycle,
    now: datetime,
    *,
    reminder_hour: int = 9,
    offsets: tuple[int, ...] = (5, 3, 1),
) -> PayrollReminderMilestone | None:
    _validate_reminder_hour(reminder_hour)
    local = in_jakarta(now)
    if local.hour < reminder_hour:
        return None
    return next(
        (item for item in reminder_milestones(cycle, offsets) if item.work_date == local.date()),
        None,
    )


def evaluated_through(
    cycle: PayrollCycle,
    now: datetime,
    ready_at: Callable[[date], datetime],
) -> date | None:
    """Return the latest contiguous cycle day whose evaluation window has ended.

    The caller owns shift/schedule semantics through ``ready_at``. This keeps the
    payroll period helper independent from attendance source rules and prevents a
    date from becoming evaluable merely because it is inside the payroll cycle.
    """
    local_now = in_jakarta(now)
    latest: date | None = None
    for work_date in cycle.period.days():
        if in_jakarta(ready_at(work_date)) > local_now:
            break
        latest = work_date
    return latest
