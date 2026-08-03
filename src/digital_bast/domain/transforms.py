from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from digital_bast.domain.errors import InvalidAchievementError, InvalidTimeError, MissingFieldError
from digital_bast.domain.identity import daily_key, task_key
from digital_bast.domain.models import (
    Attendance,
    EmployeeId,
    RecordOrigin,
    Task,
    TaskCategory,
    TaskSource,
)
from digital_bast.domain.time import in_jakarta

TITLE_FIELD: Final = "title"
ISSUE_FIELD: Final = "issue"
MAX_ACHIEVEMENT: Final = 100


@dataclass(frozen=True, slots=True)
class AttendanceInput:
    employee_id: EmployeeId
    work_date: date
    start_at: datetime | None
    end_at: datetime | None


@dataclass(frozen=True, slots=True)
class RedmineTaskInput:
    source_id: str
    employee_id: EmployeeId
    title: str
    requestor: str
    status: str
    start_date: date
    end_date: date | None
    tracker: str
    achievement: int


@dataclass(frozen=True, slots=True)
class IoTTaskInput:
    source_id: str
    employee_id: EmployeeId
    issue: str
    issue_type: str
    work_date: date
    first_responder: str
    start_at: datetime | None
    response_at: datetime | None
    close_at: datetime | None


def transform_attendance(value: AttendanceInput) -> Attendance:
    start_at = in_jakarta(value.start_at) if value.start_at is not None else None
    end_at = in_jakarta(value.end_at) if value.end_at is not None else None
    if start_at is not None and start_at.date() != value.work_date:
        raise InvalidTimeError(start_at.isoformat())
    if start_at is not None and end_at is not None and end_at <= start_at:
        raise InvalidTimeError(end_at.isoformat())
    return Attendance(
        daily_key("attendance", value.work_date, value.employee_id),
        value.employee_id,
        value.work_date,
        start_at,
        end_at,
        RecordOrigin.PIPELINE,
    )


def transform_redmine_task(value: RedmineTaskInput) -> Task:
    title = value.title.strip()
    if not title:
        raise MissingFieldError(TITLE_FIELD)
    if not 0 <= value.achievement <= MAX_ACHIEVEMENT:
        raise InvalidAchievementError(value.achievement)
    category = TaskCategory.RELEASE if value.tracker == "DIGI-SI" else TaskCategory.CODE_QUALITY
    return Task(
        task_key(value.start_date, value.employee_id, title, TaskSource.REDMINE, value.source_id),
        value.employee_id,
        value.start_date,
        title,
        value.requestor,
        value.status,
        category,
        TaskSource.REDMINE,
        value.source_id,
        None,
        None,
        None,
        None,
        value.end_date,
        value.achievement,
        RecordOrigin.PIPELINE,
    )


def transform_iot_task(value: IoTTaskInput) -> Task:
    issue = value.issue.strip()
    if not issue:
        raise MissingFieldError(ISSUE_FIELD)
    start_at = in_jakarta(value.start_at) if value.start_at is not None else None
    response_at = in_jakarta(value.response_at) if value.response_at is not None else None
    close_at = in_jakarta(value.close_at) if value.close_at is not None else None
    if start_at is not None and start_at.date() != value.work_date:
        raise InvalidTimeError(start_at.isoformat())
    if start_at is not None and response_at is not None and response_at < start_at:
        raise InvalidTimeError(response_at.isoformat())
    if start_at is not None and close_at is not None and close_at < start_at:
        raise InvalidTimeError(close_at.isoformat())
    return Task(
        task_key(
            value.work_date,
            value.employee_id,
            issue,
            TaskSource.GOOGLE_SHEET,
            value.source_id,
        ),
        value.employee_id,
        value.work_date,
        issue,
        "User",
        "Closed",
        TaskCategory.IOT,
        TaskSource.GOOGLE_SHEET,
        value.source_id,
        value.first_responder,
        start_at,
        response_at,
        close_at,
        close_at.date() if close_at is not None else value.work_date,
        MAX_ACHIEVEMENT,
        RecordOrigin.PIPELINE,
    )
