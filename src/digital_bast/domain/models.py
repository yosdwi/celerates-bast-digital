from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import NewType

from digital_bast.domain.errors import InvalidMonthError

EmployeeId = NewType("EmployeeId", str)
RecordKey = NewType("RecordKey", str)
SourceId = NewType("SourceId", str)
MAX_MONTH = 12


class EmployeeRole(StrEnum):
    DEVELOPER = "Developer"
    IOT_OPERATIONS = "IoT Operations"


class RecordOrigin(StrEnum):
    PIPELINE = "pipeline"
    MANUAL = "manual"


class TaskSource(StrEnum):
    REDMINE = "redmine"
    GOOGLE_SHEET = "google_sheet"


class TaskCategory(StrEnum):
    CODE_QUALITY = "Detail Aktivitas Kualitas Kode"
    RELEASE = "Detail Aktivitas Waktu Rilis Fitur"
    IOT = "IoT Operations"


class EntityKind(StrEnum):
    HOLIDAY = "holiday"
    ATTENDANCE = "attendance"
    TASK = "task"
    SCHEDULE = "schedule"
    TIMESHEET = "timesheet"


@dataclass(frozen=True, slots=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if self.year < 1 or not 1 <= self.month <= MAX_MONTH:
            raise InvalidMonthError(self.year, self.month)


@dataclass(frozen=True, slots=True)
class Employee:
    id: EmployeeId
    external_id: str
    name: str
    role: EmployeeRole


@dataclass(frozen=True, slots=True)
class Holiday:
    key: RecordKey
    work_date: date
    name: str
    origin: RecordOrigin = RecordOrigin.PIPELINE


@dataclass(frozen=True, slots=True)
class Attendance:
    key: RecordKey
    employee_id: EmployeeId
    work_date: date
    start_at: datetime | None
    end_at: datetime | None
    origin: RecordOrigin


@dataclass(frozen=True, slots=True)
class Task:
    key: RecordKey
    employee_id: EmployeeId
    work_date: date
    title: str
    requestor: str
    status: str
    category: TaskCategory
    source: TaskSource
    source_id: str
    assignee: str | None
    start_at: datetime | None
    response_at: datetime | None
    close_at: datetime | None
    end_date: date | None
    achievement: int
    origin: RecordOrigin
    issue_type: str | None = None


@dataclass(frozen=True, slots=True)
class Schedule:
    key: RecordKey
    employee_id: EmployeeId
    work_date: date
    shift_name: str | None
    origin: RecordOrigin


@dataclass(frozen=True, slots=True)
class Timesheet:
    key: RecordKey
    employee_id: EmployeeId
    work_date: date
    calendar_month: str
    activity: str
    project: str
    is_holiday: bool
    remarks: str
    attendance_key: RecordKey | None
    task_keys: tuple[RecordKey, ...]
    origin: RecordOrigin


DomainRecord = Holiday | Attendance | Task | Schedule | Timesheet
