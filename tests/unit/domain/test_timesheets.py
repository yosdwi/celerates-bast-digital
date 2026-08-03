from datetime import date, datetime
from zoneinfo import ZoneInfo

from digital_bast.domain.models import (
    Attendance,
    Employee,
    EmployeeId,
    EmployeeRole,
    Holiday,
    Month,
    RecordKey,
    RecordOrigin,
    Schedule,
    Task,
    TaskCategory,
    TaskSource,
)
from digital_bast.domain.timesheets import (
    TimesheetGeneration,
    TimesheetOptions,
    generate_monthly_timesheets,
)


def test_monthly_timesheets_link_attendance_and_all_daily_tasks() -> None:
    jakarta = ZoneInfo("Asia/Jakarta")
    employee = Employee(EmployeeId("17"), "NRP17", "Ani", EmployeeRole.DEVELOPER)
    attendance = Attendance(
        RecordKey("attendance:2026-08-03:17"),
        employee.id,
        date(2026, 8, 3),
        datetime(2026, 8, 3, 8, tzinfo=jakarta),
        datetime(2026, 8, 3, 17, tzinfo=jakarta),
        RecordOrigin.PIPELINE,
    )
    tasks = tuple(
        Task(
            RecordKey(f"task:{index}"),
            employee.id,
            date(2026, 8, 3),
            f"Task {index}",
            "Lead",
            "Closed",
            TaskCategory.CODE_QUALITY,
            TaskSource.REDMINE,
            str(index),
            None,
            None,
            None,
            None,
            date(2026, 8, 3),
            100,
            RecordOrigin.PIPELINE,
        )
        for index in range(2)
    )

    records = generate_monthly_timesheets(
        TimesheetGeneration(
            (employee,),
            Month(2026, 8),
            (attendance,),
            tasks,
            (),
            (),
            TimesheetOptions("Development", "Weekend", "IoT Operations", "PAMA"),
        )
    )
    target = next(record for record in records if record.work_date == date(2026, 8, 3))

    assert target.attendance_key == attendance.key
    assert target.task_keys == tuple(task.key for task in tasks)
    assert len(records) == 31


def test_regular_weekend_and_public_holiday_are_marked_off() -> None:
    employee = Employee(EmployeeId("17"), "NRP17", "Ani", EmployeeRole.DEVELOPER)
    holiday = Holiday(RecordKey("holiday:2026-08-17"), date(2026, 8, 17), "Independence Day")

    records = generate_monthly_timesheets(
        TimesheetGeneration(
            (employee,),
            Month(2026, 8),
            (),
            (),
            (holiday,),
            (),
            TimesheetOptions("Development", "Weekend", "IoT Operations", "PAMA"),
        )
    )

    assert next(row for row in records if row.work_date == date(2026, 8, 2)).is_holiday
    independence_day = next(row for row in records if row.work_date == date(2026, 8, 17))

    assert independence_day.remarks == "Independence Day"


def test_iot_schedule_controls_off_day_across_month_boundary() -> None:
    employee = Employee(EmployeeId("95"), "NRP95", "Tama", EmployeeRole.IOT_OPERATIONS)
    schedule = Schedule(
        RecordKey("schedule:2026-02-28:95"),
        employee.id,
        date(2026, 2, 28),
        "SHIFT 1",
        RecordOrigin.PIPELINE,
    )

    records = generate_monthly_timesheets(
        TimesheetGeneration(
            (employee,),
            Month(2026, 2),
            (),
            (),
            (),
            (schedule,),
            TimesheetOptions("Development", "Weekend", "IoT Operations", "PAMA"),
        )
    )

    assert len(records) == 28
    assert records[0].is_holiday
    assert records[-1].is_holiday is False
