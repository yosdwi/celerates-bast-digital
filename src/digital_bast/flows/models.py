from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final, Self, override

_MAX_MONTH: Final = 12


class InvalidPeriodError(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value: str = value

    @override
    def __str__(self) -> str:
        return f"invalid period {self.value!r}; expected YYYY-MM"


@dataclass(frozen=True, slots=True)
class Period:
    year: int
    month: int
    lookback_months: int = 0

    @classmethod
    def parse(cls, value: str) -> Self:
        match = re.fullmatch(r"(?P<year>\d{4})-(?P<month>\d{2})", value)
        if match is None:
            raise InvalidPeriodError(value)
        year = int(match.group("year"))
        month = int(match.group("month"))
        if not 1 <= month <= _MAX_MONTH:
            raise InvalidPeriodError(value)
        return cls(year=year, month=month)

    @property
    def start(self) -> date:
        year, month = self.year, self.month - self.lookback_months
        while month < 1:
            month += _MAX_MONTH
            year -= 1
        return date(year, month, 1)

    @property
    def end(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @override
    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class Operation(StrEnum):
    ATTENDANCE_IMPORT = "attendance-import"
    REDMINE_IMPORT = "redmine-import"
    IOT_TASK_IMPORT = "iot-task-import"
    RECONCILIATION = "reconciliation"
    HOLIDAY_SYNC = "holiday-sync"
    SCHEDULE_SYNC = "schedule-sync"
    TIMESHEET_GENERATION = "timesheet-generation"
    IOT_PIC_UPDATE = "iot-pic-update"


@dataclass(frozen=True, slots=True)
class StepSummary:
    operation: Operation
    read: int
    written: int
    unchanged: int = 0
    locked: int = 0


@dataclass(frozen=True, slots=True)
class RunSummary:
    flow: str
    period: Period
    steps: tuple[StepSummary, ...]

    @property
    def read(self) -> int:
        return sum(step.read for step in self.steps)

    @property
    def written(self) -> int:
        return sum(step.written for step in self.steps)

    @property
    def unchanged(self) -> int:
        return sum(step.unchanged for step in self.steps)

    @property
    def locked(self) -> int:
        return sum(step.locked for step in self.steps)
