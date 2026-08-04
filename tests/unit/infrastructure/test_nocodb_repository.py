from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from digital_bast.domain.identity import daily_key, task_key
from digital_bast.domain.models import (
    EmployeeId,
    Holiday,
    RecordKey,
    RecordOrigin,
    Schedule,
    Task,
    TaskCategory,
    TaskSource,
    Timesheet,
)
from digital_bast.infrastructure.nocodb_repository import (
    _from_utc_naive,
    _holiday_from_row,
    _holiday_to_row,
    _is_locked,
    _schedule_from_row,
    _schedule_to_row,
    _task_from_row,
    _task_table,
    _task_to_row,
    _timesheet_from_row,
    _timesheet_to_row,
    _to_utc_naive,
)

JAKARTA = ZoneInfo("Asia/Jakarta")
_SYSTEM_ID = "us6iaj6psn2koj3r"


def test_to_utc_naive_shifts_jakarta_time_back_seven_hours() -> None:
    value = datetime(2026, 7, 8, 23, 13, tzinfo=JAKARTA)

    result = _to_utc_naive(value)

    assert result == datetime(2026, 7, 8, 16, 13)  # noqa: DTZ001
    assert result is not None
    assert result.tzinfo is None


def test_from_utc_naive_shifts_stored_value_forward_to_jakarta() -> None:
    stored = datetime(2026, 7, 8, 16, 13)  # noqa: DTZ001

    result = _from_utc_naive(stored)

    assert result == datetime(2026, 7, 8, 23, 13, tzinfo=JAKARTA)


def test_utc_round_trip_is_lossless() -> None:
    original = datetime(2026, 7, 8, 23, 13, tzinfo=JAKARTA)

    round_tripped = _from_utc_naive(_to_utc_naive(original))

    assert round_tripped == original


def test_to_utc_naive_and_from_utc_naive_pass_through_none() -> None:
    assert _to_utc_naive(None) is None
    assert _from_utc_naive(None) is None


def test_is_locked_when_updated_by_is_system_account() -> None:
    row = {"updated_by": _SYSTEM_ID}
    assert _is_locked(row, _SYSTEM_ID) is False


def test_is_locked_when_updated_by_is_a_human() -> None:
    row = {"updated_by": "managedservice@celerates.com"}
    assert _is_locked(row, _SYSTEM_ID) is True


def test_is_locked_when_updated_by_is_null_treats_as_unclaimed() -> None:
    row = {"updated_by": None}
    assert _is_locked(row, _SYSTEM_ID) is False


def test_is_locked_respects_is_manual_edit_flag_even_when_system_owned() -> None:
    row = {"updated_by": _SYSTEM_ID, "IsManualEdit": "true"}
    assert _is_locked(row, _SYSTEM_ID) is True


def test_is_locked_is_manual_edit_false_does_not_lock() -> None:
    row = {"updated_by": _SYSTEM_ID, "IsManualEdit": "false"}
    assert _is_locked(row, _SYSTEM_ID) is False


def test_task_table_routes_by_source() -> None:
    assert _task_table(TaskSource.GOOGLE_SHEET) == "Tasklist IoT Operations"
    assert _task_table(TaskSource.REDMINE) == "Tasklist Developer"


def test_holiday_round_trip() -> None:
    holiday = Holiday(
        key=RecordKey("holiday:2026-07-08"),
        work_date=date(2026, 7, 8),
        name="Idul Adha",
    )

    row = _holiday_to_row(holiday)
    assert row["Unique_Key"] == "holiday:2026-07-08"
    assert row["Date"] == date(2026, 7, 8)
    assert row["Description"] == "Idul Adha"
    assert row["Day_Name"] == "Wednesday"

    restored = _holiday_from_row(row, locked=False)
    assert restored.key == holiday.key
    assert restored.work_date == holiday.work_date
    assert restored.name == holiday.name
    assert restored.origin is RecordOrigin.PIPELINE


def test_holiday_from_row_marks_manual_origin_when_locked() -> None:
    row = {"Date": date(2026, 7, 8), "Description": "Idul Adha"}

    restored = _holiday_from_row(row, locked=True)

    assert restored.origin is RecordOrigin.MANUAL


def test_holiday_from_row_ignores_unique_key_and_uses_date_column() -> None:
    row = {
        "Unique_Key": "some-unrelated-legacy-hash",
        "Date": date(2026, 7, 8),
        "Description": "Idul Adha",
    }

    restored = _holiday_from_row(row, locked=False)

    assert restored.key == RecordKey("holiday:2026-07-08")
    assert restored.work_date == date(2026, 7, 8)


def test_task_round_trip_for_iot_source() -> None:
    task = Task(
        key=task_key(
            date(2026, 7, 8),
            EmployeeId("112"),
            "Pengecekan deployment penambahan field rpm",
            TaskSource.GOOGLE_SHEET.value,
            "2026-07-08_112_pengecekan deployment penambahan field rpm",
        ),
        employee_id=EmployeeId("112"),
        work_date=date(2026, 7, 8),
        title="Pengecekan deployment penambahan field rpm",
        requestor="User",
        status="Closed",
        category=TaskCategory.IOT,
        source=TaskSource.GOOGLE_SHEET,
        source_id="2026-07-08_112_pengecekan deployment penambahan field rpm",
        assignee="Bayu Sutra",
        start_at=datetime(2026, 7, 8, 23, 13, tzinfo=JAKARTA),
        response_at=datetime(2026, 7, 8, 23, 17, tzinfo=JAKARTA),
        close_at=datetime(2026, 7, 8, 23, 13, tzinfo=JAKARTA),
        end_date=date(2026, 7, 8),
        achievement=100,
        origin=RecordOrigin.PIPELINE,
        issue_type="Request HO",
    )

    row = _task_to_row(task)
    assert row["Id_Key"] == "2026-07-08_112"
    assert row["Task_List"] == task.title
    assert row["Kategori"] == "Request HO"
    assert row["Pencapaian"] == 100.0
    assert row["Start_Time"] == datetime(2026, 7, 8, 16, 13)  # noqa: DTZ001
    assert row["Close_Time"] == datetime(2026, 7, 8, 16, 13)  # noqa: DTZ001

    restored = _task_from_row("Tasklist IoT Operations", row, locked=False)
    assert restored.key == task.key
    assert restored.employee_id == task.employee_id
    assert restored.work_date == task.work_date
    assert restored.title == task.title
    assert restored.source is TaskSource.GOOGLE_SHEET
    assert restored.start_at == task.start_at
    assert restored.close_at == task.close_at
    assert restored.achievement == 100
    assert restored.issue_type == "Request HO"
    assert restored.category is TaskCategory.IOT


def test_task_to_row_falls_back_to_category_when_issue_type_missing() -> None:
    task = Task(
        key=task_key(date(2026, 7, 8), EmployeeId("112"), "Noface", "google_sheet", "x"),
        employee_id=EmployeeId("112"),
        work_date=date(2026, 7, 8),
        title="Noface",
        requestor="User",
        status="Closed",
        category=TaskCategory.IOT,
        source=TaskSource.GOOGLE_SHEET,
        source_id="x",
        assignee=None,
        start_at=None,
        response_at=None,
        close_at=None,
        end_date=None,
        achievement=100,
        origin=RecordOrigin.PIPELINE,
    )

    row = _task_to_row(task)

    assert row["Kategori"] == TaskCategory.IOT.value


def test_task_from_row_reads_legacy_kategori_as_issue_type() -> None:
    row = {
        "Date": date(2026, 8, 3),
        "Id_Key": "2026-08-03_97",
        "Task_List": "noface",
        "Kategori": "No Face ANF",
        "Pencapaian": 100.0,
    }

    restored = _task_from_row("Tasklist IoT Operations", row, locked=False)

    assert restored.issue_type == "No Face ANF"
    assert restored.category is TaskCategory.IOT


def test_task_to_row_omits_time_columns_for_redmine_source() -> None:
    task = Task(
        key=RecordKey("task:2026-07-08:76:def456"),
        employee_id=EmployeeId("76"),
        work_date=date(2026, 7, 8),
        title="Fix bug",
        requestor="User",
        status="Open",
        category=TaskCategory.CODE_QUALITY,
        source=TaskSource.REDMINE,
        source_id="ignored-on-write",
        assignee=None,
        start_at=None,
        response_at=None,
        close_at=None,
        end_date=None,
        achievement=50,
        origin=RecordOrigin.PIPELINE,
    )

    row = _task_to_row(task)

    assert "Start_Time" not in row
    assert "Response_Time" not in row
    assert "Close_Time" not in row


def test_task_from_row_routes_source_by_table() -> None:
    row = {
        "Date": date(2026, 7, 8),
        "Id_Key": "2026-07-08_76",
        "Task_List": "Fix bug",
        "Pencapaian": 50.0,
    }

    restored = _task_from_row("Tasklist Developer", row, locked=False)

    assert restored.source is TaskSource.REDMINE
    assert restored.employee_id == EmployeeId("76")
    assert restored.achievement == 50


def test_schedule_round_trip() -> None:
    schedule = Schedule(
        key=daily_key("schedule", date(2026, 7, 8), EmployeeId("102")),
        employee_id=EmployeeId("102"),
        work_date=date(2026, 7, 8),
        shift_name=None,
        origin=RecordOrigin.PIPELINE,
    )

    row = _schedule_to_row(schedule)
    assert row["Date_Shifting"] == date(2026, 7, 8)
    row["_employee_id"] = 102

    restored = _schedule_from_row(row, locked=False)
    assert restored.key == schedule.key
    assert restored.employee_id == schedule.employee_id
    assert restored.shift_name is None


def test_schedule_from_row_reads_looked_up_shift_name() -> None:
    row = {"Date": date(2026, 7, 8), "_employee_id": 102, "Shift_Name": "SHIFT 1"}

    restored = _schedule_from_row(row, locked=False)

    assert restored.shift_name == "SHIFT 1"


def test_timesheet_round_trip() -> None:
    timesheet = Timesheet(
        key=daily_key("timesheet", date(2026, 7, 8), EmployeeId("102")),
        employee_id=EmployeeId("102"),
        work_date=date(2026, 7, 8),
        calendar_month="2026-07",
        activity="P00-Project",
        project="Some Project",
        is_holiday=False,
        remarks="Working Day",
        attendance_key=None,
        task_keys=(),
        origin=RecordOrigin.PIPELINE,
    )

    row = _timesheet_to_row(timesheet)
    assert row["holiday"] == "false"
    row["_employee_id"] = 102

    restored = _timesheet_from_row(row, locked=False)
    assert restored.key == timesheet.key
    assert restored.employee_id == timesheet.employee_id
    assert restored.calendar_month == timesheet.calendar_month
    assert restored.is_holiday is False
    assert restored.attendance_key is None
    assert restored.task_keys == ()


def test_timesheet_to_row_marks_holiday_true() -> None:
    timesheet = Timesheet(
        key=RecordKey("timesheet:2026-07-08:102"),
        employee_id=EmployeeId("102"),
        work_date=date(2026, 7, 8),
        calendar_month="2026-07",
        activity="",
        project="",
        is_holiday=True,
        remarks="Weekend",
        attendance_key=None,
        task_keys=(),
        origin=RecordOrigin.PIPELINE,
    )

    row = _timesheet_to_row(timesheet)

    assert row["holiday"] == "true"
    assert _timesheet_from_row(row, locked=False).is_holiday is True
