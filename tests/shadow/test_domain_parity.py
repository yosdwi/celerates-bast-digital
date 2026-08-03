from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from digital_bast.domain.identity import daily_key, task_key
from digital_bast.domain.models import (
    Attendance,
    Employee,
    EmployeeId,
    EmployeeRole,
    Month,
    RecordOrigin,
    Schedule,
    TaskCategory,
)
from digital_bast.domain.reference import HolidayInput, generate_iot_schedules, transform_holiday
from digital_bast.domain.rules import merge_pipeline_record
from digital_bast.domain.scheduling import UPDATE_IOT_PIC, SyncSchedule
from digital_bast.domain.timesheets import (
    TimesheetGeneration,
    TimesheetOptions,
    generate_monthly_timesheets,
)
from digital_bast.domain.transforms import (
    AttendanceInput,
    IoTTaskInput,
    RedmineTaskInput,
    transform_attendance,
    transform_iot_task,
    transform_redmine_task,
)

JAKARTA = ZoneInfo("Asia/Jakarta")


def test_v2_parity_transforms_when_sanitized_step01_step02_and_step03_fixture_is_replayed() -> None:
    given = (
        transform_holiday(HolidayInput(date(2024, 2, 29), "Synthetic National Holiday")),
        transform_attendance(
            AttendanceInput(
                EmployeeId("emp-dev-001"),
                date(2024, 2, 1),
                datetime(2024, 2, 1, 8, 15, tzinfo=JAKARTA),
                datetime(2024, 2, 1, 17, 15, tzinfo=JAKARTA),
            )
        ),
        transform_redmine_task(
            RedmineTaskInput(
                "synthetic-redmine-001",
                EmployeeId("emp-dev-001"),
                "Release: Alpha/1",
                "Synthetic Requestor",
                "Closed",
                date(2024, 2, 1),
                date(2024, 2, 1),
                "DIGI-SI",
                100,
            )
        ),
        transform_iot_task(
            IoTTaskInput(
                "synthetic-iot-001",
                EmployeeId("emp-iot-001"),
                "Sensor alert: zone/1",
                "Incident",
                date(2024, 2, 29),
                "Operator One",
                datetime(2024, 2, 29, 7, 5, tzinfo=JAKARTA),
                datetime(2024, 2, 29, 7, 15, tzinfo=JAKARTA),
                datetime(2024, 2, 29, 8, tzinfo=JAKARTA),
            )
        ),
    )

    when = given

    holiday, attendance, redmine_task, iot_task = when
    assert str(holiday.key) == "holiday:2024-02-29"
    assert str(attendance.key) == "attendance:2024-02-01:emp-dev-001"
    assert attendance.start_at == datetime(2024, 2, 1, 8, 15, tzinfo=JAKARTA)
    assert redmine_task.category is TaskCategory.RELEASE
    assert redmine_task.work_date == date(2024, 2, 1)
    assert iot_task.category is TaskCategory.IOT
    assert iot_task.assignee == "Operator One"
    assert iot_task.status == "Closed"
    assert iot_task.response_at == datetime(2024, 2, 29, 7, 15, tzinfo=JAKARTA)


def test_v2_parity_preserves_manual_attendance_when_duplicate_pipeline_rows_are_reordered() -> None:
    given = (
        Attendance(
            daily_key("attendance", date(2024, 2, 1), EmployeeId("emp-dev-001")),
            EmployeeId("emp-dev-001"),
            date(2024, 2, 1),
            datetime(2024, 2, 1, 7, 30, tzinfo=JAKARTA),
            datetime(2024, 2, 1, 16, 30, tzinfo=JAKARTA),
            RecordOrigin.MANUAL,
        ),
        tuple(
            transform_attendance(
                AttendanceInput(
                    EmployeeId("emp-dev-001"),
                    date(2024, 2, 1),
                    start_at,
                    end_at,
                )
            )
            for start_at, end_at in (
                (
                    datetime(2024, 2, 1, 8, tzinfo=JAKARTA),
                    datetime(2024, 2, 1, 17, tzinfo=JAKARTA),
                ),
                (
                    datetime(2024, 2, 1, 8, 15, tzinfo=JAKARTA),
                    datetime(2024, 2, 1, 17, 15, tzinfo=JAKARTA),
                ),
            )
        ),
    )

    existing, pipeline_rows = given
    when = tuple(merge_pipeline_record(existing, candidate) for candidate in pipeline_rows[::-1])

    assert len({result.record.key for result in when}) == 1
    assert all(result.locked for result in when)
    assert all(result.record == existing for result in when)
    assert all(result.changed is False for result in when)


def test_v2_parity_generates_leap_month_timesheets_and_preserves_manual_timesheet() -> None:
    given = (
        (
            Employee(
                EmployeeId("emp-dev-001"),
                "SAN-DEV-001",
                "Developer One",
                EmployeeRole.DEVELOPER,
            ),
            Employee(
                EmployeeId("emp-iot-001"),
                "SAN-IOT-001",
                "Operator One",
                EmployeeRole.IOT_OPERATIONS,
            ),
        ),
        Month(2024, 2),
        transform_holiday(HolidayInput(date(2024, 2, 29), "Synthetic National Holiday")),
        TimesheetOptions(
            "Synthetic weekday activity",
            "Synthetic weekend activity",
            "Synthetic IoT activity",
            "Synthetic Project",
        ),
    )

    employees, period, holiday, options = given
    schedules = generate_iot_schedules(employees, period)
    when = generate_monthly_timesheets(
        TimesheetGeneration(
            employees,
            period,
            (),
            (),
            (holiday,),
            (
                Schedule(
                    daily_key("schedule", date(2024, 2, 29), EmployeeId("emp-iot-001")),
                    EmployeeId("emp-iot-001"),
                    date(2024, 2, 29),
                    "SHIFT PAGI",
                    RecordOrigin.PIPELINE,
                ),
            ),
            options,
        )
    )

    developer_holiday = next(
        row
        for row in when
        if row.employee_id == EmployeeId("emp-dev-001") and row.work_date == date(2024, 2, 29)
    )
    iot_holiday = next(
        row
        for row in when
        if row.employee_id == EmployeeId("emp-iot-001") and row.work_date == date(2024, 2, 29)
    )
    manual = replace(
        developer_holiday,
        remarks="Manual holiday note",
        origin=RecordOrigin.MANUAL,
    )
    manual_merge = merge_pipeline_record(manual, developer_holiday)

    assert len(schedules) == 29
    assert len(when) == 58
    assert developer_holiday.is_holiday is True
    assert developer_holiday.remarks == "Synthetic National Holiday"
    assert iot_holiday.is_holiday is False
    assert iot_holiday.remarks == "SHIFT PAGI"
    assert iot_holiday.activity == "Synthetic IoT activity"
    assert manual_merge.record == manual
    assert manual_merge.locked is True


def test_v2_task_key_is_stable_for_row_order_and_volatile_timestamps() -> None:
    given = (
        date(2024, 2, 29),
        EmployeeId("emp-dev-001"),
        "Manual: verification/entry",
    )

    work_date, employee_id, title = given
    when = {
        task_key(work_date, employee_id, title, "manual", "manual-task-001"),
        task_key(
            work_date,
            employee_id,
            "  manual:  verification/entry  ",
            "manual",
            "manual-task-001",
        ),
    }

    assert len(when) == 1
    assert str(next(iter(when))).startswith("task:2024-02-29:emp-dev-001:")


def test_v2_step10_schedule_targets_the_nightly_procedure_once_per_local_day() -> None:
    given = SyncSchedule()

    when = (
        given.next_nightly_after(datetime(2024, 2, 29, 0, 59, tzinfo=JAKARTA)),
        given.next_nightly_after(datetime(2024, 2, 29, 1, tzinfo=JAKARTA)),
    )

    assert str(UPDATE_IOT_PIC) == "public.sp_update_tasklist_iot_pic"
    assert when == (
        datetime(2024, 2, 29, 1, tzinfo=JAKARTA),
        datetime(2024, 3, 1, 1, tzinfo=JAKARTA),
    )
