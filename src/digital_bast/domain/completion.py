from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

from digital_bast.domain.errors import DomainError
from digital_bast.domain.timesheets import day_status

if TYPE_CHECKING:
    from collections.abc import Mapping

    from digital_bast.domain.models import EmployeeRole, Holiday, Schedule

MONTH_NAMES: Final = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)
CLOSED_STATUS: Final = "closed"
ATTENDANCE_MAPPING_ISSUE: Final = (
    "Mapping data attendance belum dikonfigurasi (NOCODB_ATTENDANCE_MAPPING)."
)
TASK_EVIDENCE_MAPPING_ISSUE: Final = (
    "Mapping Evidence Task List belum dikonfigurasi (NOCODB_TASK_EVIDENCE_COLUMN)."
)
NO_TASKS_ISSUE: Final = "Belum ada Task List pada periode."
NO_TASK_EVIDENCE_ISSUE: Final = "Evidence Task List belum tersedia."


class InvalidDateRangeError(DomainError):
    def __init__(self, start: date, end: date) -> None:
        super().__init__(start, end)
        self.start: date = start
        self.end: date = end

    @override
    def __str__(self) -> str:
        return f"end date {self.end.isoformat()} is before start date {self.start.isoformat()}"


class CheckState(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NEEDS_REVIEW = "needs_review"


_SEVERITY: Final = {
    CheckState.COMPLETE: 0,
    CheckState.NEEDS_REVIEW: 1,
    CheckState.INCOMPLETE: 2,
}


def worst_state(states: tuple[CheckState, ...]) -> CheckState:
    return max(states, key=lambda state: _SEVERITY[state], default=CheckState.COMPLETE)


def format_day(value: date) -> str:
    return f"{value.day} {MONTH_NAMES[value.month - 1]}"


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise InvalidDateRangeError(self.start, self.end)

    def days(self) -> tuple[date, ...]:
        span = (self.end - self.start).days + 1
        return tuple(self.start + timedelta(days=offset) for offset in range(span))

    def months(self) -> tuple[tuple[int, int], ...]:
        seen = {(day.year, day.month): None for day in self.days()}
        return tuple(seen)

    def label(self) -> str:
        if (self.start.year, self.start.month) == (self.end.year, self.end.month):
            month = MONTH_NAMES[self.start.month - 1]
            return f"{self.start.day}-{self.end.day} {month} {self.start.year}"
        start = f"{format_day(self.start)} {self.start.year}"
        return f"{start} - {format_day(self.end)} {self.end.year}"


@dataclass(frozen=True, slots=True)
class AttendanceFact:
    work_date: date
    has_clock_in: bool
    has_clock_out: bool
    has_evidence: bool


@dataclass(frozen=True, slots=True)
class TimesheetFact:
    work_date: date
    remarks: str


@dataclass(frozen=True, slots=True)
class TaskFact:
    work_date: date
    title: str
    status: str


@dataclass(frozen=True, slots=True)
class EmployeeFacts:
    employee_id: str
    name: str
    off_days: frozenset[date]
    attendance: tuple[AttendanceFact, ...]
    timesheets: tuple[TimesheetFact, ...]
    tasks: tuple[TaskFact, ...]
    task_evidence_count: int | None
    attendance_available: bool


@dataclass(frozen=True, slots=True)
class CheckResult:
    state: CheckState
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmployeeCompletion:
    employee_id: str
    name: str
    timesheet: CheckResult
    task_list: CheckResult
    evidence: CheckResult
    log_1_pama: CheckResult

    @property
    def state(self) -> CheckState:
        return worst_state(
            (
                self.timesheet.state,
                self.task_list.state,
                self.evidence.state,
                self.log_1_pama.state,
            )
        )

    @property
    def issues(self) -> tuple[str, ...]:
        return (
            *self.log_1_pama.issues,
            *self.timesheet.issues,
            *self.task_list.issues,
            *self.evidence.issues,
        )


@dataclass(frozen=True, slots=True)
class CompletionReport:
    period: DateRange
    employees: tuple[EmployeeCompletion, ...]

    @property
    def state(self) -> CheckState:
        return worst_state(tuple(employee.state for employee in self.employees))


def resolve_off_days(
    role: EmployeeRole,
    period: DateRange,
    holidays: Mapping[date, Holiday],
    schedules: Mapping[date, Schedule],
) -> frozenset[date]:
    return frozenset(
        work_date
        for work_date in period.days()
        if day_status(role, work_date.weekday(), holidays.get(work_date), schedules.get(work_date))[
            0
        ]
    )


def _missing_clock_label(record: AttendanceFact) -> str:
    if not record.has_clock_in and not record.has_clock_out:
        return "Clock In dan Clock Out belum terisi"
    return "Clock In belum terisi" if not record.has_clock_in else "Clock Out belum terisi"


def _log_1_pama(facts: EmployeeFacts, period: DateRange) -> tuple[CheckResult, frozenset[date]]:
    if not facts.attendance_available:
        return CheckResult(CheckState.NEEDS_REVIEW, (ATTENDANCE_MAPPING_ISSUE,)), frozenset()
    by_day = {record.work_date: record for record in facts.attendance}
    issues: list[str] = []
    invalid: set[date] = set()
    for work_date in period.days():
        if work_date in facts.off_days:
            continue
        record = by_day.get(work_date)
        if record is None:
            issues.append(f"{format_day(work_date)} — Data attendance belum tersedia.")
            invalid.add(work_date)
            continue
        if record.has_clock_in and record.has_clock_out:
            continue
        if record.has_evidence:
            continue
        issues.append(
            f"{format_day(work_date)} — {_missing_clock_label(record)} "
            "dan Evidence Attendance belum tersedia."
        )
        invalid.add(work_date)
    state = CheckState.INCOMPLETE if issues else CheckState.COMPLETE
    return CheckResult(state, tuple(issues)), frozenset(invalid)


def _timesheet(
    facts: EmployeeFacts,
    period: DateRange,
    invalid_log_days: frozenset[date],
) -> CheckResult:
    by_day = {record.work_date: record for record in facts.timesheets}
    issues: list[str] = []
    for work_date in period.days():
        label = format_day(work_date)
        record = by_day.get(work_date)
        if work_date in facts.off_days:
            if record is None:
                issues.append(f"{label} — Timesheet untuk jadwal OFF belum tersedia.")
            elif not record.remarks.strip():
                issues.append(f"{label} — Keterangan OFF pada Timesheet belum terisi.")
            continue
        if work_date in invalid_log_days:
            issues.append(f"{label} — Timesheet belum dapat lengkap karena Log 1 PAMA belum valid.")
            continue
        if record is None:
            issues.append(f"{label} — Timesheet belum tersedia.")
    state = CheckState.INCOMPLETE if issues else CheckState.COMPLETE
    return CheckResult(state, tuple(issues))


def _task_list(facts: EmployeeFacts) -> CheckResult:
    if not facts.tasks:
        return CheckResult(CheckState.NEEDS_REVIEW, (NO_TASKS_ISSUE,))
    issues = tuple(
        f'Task "{task.title}" belum Closed.'
        for task in facts.tasks
        if task.status.strip().casefold() != CLOSED_STATUS
    )
    state = CheckState.INCOMPLETE if issues else CheckState.COMPLETE
    return CheckResult(state, issues)


def _evidence(facts: EmployeeFacts) -> CheckResult:
    if facts.task_evidence_count is None:
        return CheckResult(CheckState.NEEDS_REVIEW, (TASK_EVIDENCE_MAPPING_ISSUE,))
    if facts.task_evidence_count > 0:
        return CheckResult(CheckState.COMPLETE, ())
    return CheckResult(CheckState.INCOMPLETE, (NO_TASK_EVIDENCE_ISSUE,))


def evaluate_employee(facts: EmployeeFacts, period: DateRange) -> EmployeeCompletion:
    log_result, invalid_log_days = _log_1_pama(facts, period)
    return EmployeeCompletion(
        employee_id=facts.employee_id,
        name=facts.name,
        timesheet=_timesheet(facts, period, invalid_log_days),
        task_list=_task_list(facts),
        evidence=_evidence(facts),
        log_1_pama=log_result,
    )


def evaluate_completion(
    period: DateRange,
    facts: tuple[EmployeeFacts, ...],
) -> CompletionReport:
    return CompletionReport(
        period=period,
        employees=tuple(evaluate_employee(item, period) for item in facts),
    )
