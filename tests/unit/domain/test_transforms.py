from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from digital_bast.domain.errors import InvalidTimeError, MissingFieldError
from digital_bast.domain.models import EmployeeId, RecordOrigin, TaskCategory, TaskSource
from digital_bast.domain.transforms import (
    AttendanceInput,
    IoTTaskInput,
    RedmineTaskInput,
    transform_attendance,
    transform_iot_task,
    transform_redmine_task,
)


def test_attendance_transform_normalizes_to_asia_jakarta() -> None:
    row = AttendanceInput(
        employee_id=EmployeeId("17"),
        work_date=date(2026, 8, 1),
        start_at=datetime.fromisoformat("2026-08-01T01:00:00+00:00"),
        end_at=datetime.fromisoformat("2026-08-01T09:00:00+00:00"),
    )

    attendance = transform_attendance(row)

    assert attendance.start_at == datetime(2026, 8, 1, 8, tzinfo=ZoneInfo("Asia/Jakarta"))


def test_redmine_tracker_maps_to_release_category() -> None:
    row = RedmineTaskInput(
        source_id="991",
        employee_id=EmployeeId("17"),
        title="Release API",
        requestor="Product",
        status="Closed",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        tracker="DIGI-SI",
        achievement=80,
    )

    task = transform_redmine_task(row)

    assert task.category is TaskCategory.RELEASE
    assert task.source is TaskSource.REDMINE


def test_iot_task_uses_first_responder_and_closed_defaults() -> None:
    jakarta = ZoneInfo("Asia/Jakarta")
    row = IoTTaskInput(
        source_id="sheet-8",
        employee_id=EmployeeId("95"),
        issue="Sensor offline",
        issue_type="Incident",
        work_date=date(2026, 8, 1),
        first_responder="Tama",
        start_at=datetime(2026, 8, 1, 10, tzinfo=jakarta),
        response_at=datetime(2026, 8, 1, 10, 5, tzinfo=jakarta),
        close_at=datetime(2026, 8, 1, 10, 30, tzinfo=jakarta),
    )

    task = transform_iot_task(row)

    assert (task.requestor, task.status, task.assignee, task.origin) == (
        "User",
        "Closed",
        "Tama",
        RecordOrigin.PIPELINE,
    )


def test_iot_task_rejects_missing_issue() -> None:
    row = IoTTaskInput(
        source_id="sheet-8",
        employee_id=EmployeeId("95"),
        issue=" ",
        issue_type="Incident",
        work_date=date(2026, 8, 1),
        first_responder="Tama",
        start_at=None,
        response_at=None,
        close_at=None,
    )

    with pytest.raises(MissingFieldError):
        _ = transform_iot_task(row)


def test_attendance_rejects_naive_datetime() -> None:
    row = AttendanceInput(
        employee_id=EmployeeId("17"),
        work_date=date(2026, 8, 1),
        start_at=datetime.fromisoformat("2026-08-01T08:00:00"),
        end_at=None,
    )

    with pytest.raises(InvalidTimeError):
        _ = transform_attendance(row)
