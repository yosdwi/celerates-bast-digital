from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from digital_bast.domain.identity import daily_key, task_key
from digital_bast.domain.models import (
    Attendance,
    EmployeeId,
    RecordKey,
    RecordOrigin,
)
from digital_bast.domain.rules import merge_pipeline_record


def test_task_key_is_stable_when_description_spacing_and_case_change() -> None:
    employee_id = EmployeeId("42")

    first = task_key(date(2026, 8, 1), employee_id, " Deploy  API ", "redmine", "991")
    second = task_key(date(2026, 8, 1), employee_id, "deploy api", "redmine", "991")

    assert first == second


def test_task_key_changes_for_distinct_source_records_with_same_title() -> None:
    employee_id = EmployeeId("42")

    first = task_key(date(2026, 8, 1), employee_id, "Deploy API", "redmine", "991")
    second = task_key(date(2026, 8, 1), employee_id, "Deploy API", "redmine", "992")

    assert first != second


def test_daily_key_changes_at_jakarta_month_boundary() -> None:
    jakarta = ZoneInfo("Asia/Jakarta")

    july = daily_key("attendance", datetime(2026, 7, 31, 23, 59, tzinfo=jakarta).date(), "9")
    august = daily_key("attendance", datetime(2026, 8, 1, 0, 0, tzinfo=jakarta).date(), "9")

    assert july != august


def test_manual_record_wins_and_locks_the_entire_record() -> None:
    jakarta = ZoneInfo("Asia/Jakarta")
    existing = Attendance(
        key=RecordKey("attendance:2026-08-01:42"),
        employee_id=EmployeeId("42"),
        work_date=date(2026, 8, 1),
        start_at=datetime(2026, 8, 1, 9, tzinfo=jakarta),
        end_at=datetime(2026, 8, 1, 17, tzinfo=jakarta),
        origin=RecordOrigin.MANUAL,
    )
    incoming = replace(
        existing,
        start_at=datetime(2026, 8, 1, 8, tzinfo=jakarta),
        origin=RecordOrigin.PIPELINE,
    )

    result = merge_pipeline_record(existing, incoming)

    assert result.record == existing
    assert result.changed is False
    assert result.locked is True
