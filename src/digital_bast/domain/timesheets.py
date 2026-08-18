from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from digital_bast.domain.identity import daily_key
from digital_bast.domain.models import (
    Attendance,
    Employee,
    EmployeeId,
    EmployeeRole,
    Holiday,
    Month,
    RecordOrigin,
    Schedule,
    Task,
    Timesheet,
)
from digital_bast.domain.time import month_dates

if TYPE_CHECKING:
    from datetime import date

WEEKEND_START: Final = 5


@dataclass(frozen=True, slots=True)
class TimesheetOptions:
    weekday_activity: str
    weekend_activity: str
    iot_activity: str
    default_project: str


@dataclass(frozen=True, slots=True)
class TimesheetGeneration:
    employees: tuple[Employee, ...]
    period: Month
    attendance: tuple[Attendance, ...]
    tasks: tuple[Task, ...]
    holidays: tuple[Holiday, ...]
    schedules: tuple[Schedule, ...]
    options: TimesheetOptions


def generate_monthly_timesheets(request: TimesheetGeneration) -> tuple[Timesheet, ...]:
    attendance_by_day = {
        (record.employee_id, record.work_date): record
        for record in sorted(request.attendance, key=lambda item: str(item.key))
    }
    tasks_by_day: dict[tuple[EmployeeId, date], dict[str, Task]] = {}
    for task in sorted(request.tasks, key=lambda item: str(item.key)):
        tasks_by_day.setdefault((task.employee_id, task.work_date), {})[str(task.key)] = task
    holiday_by_day = {
        record.work_date: record
        for record in sorted(request.holidays, key=lambda item: str(item.key))
    }
    schedule_by_day = {
        (record.employee_id, record.work_date): record
        for record in sorted(request.schedules, key=lambda item: str(item.key))
    }
    rows: list[Timesheet] = []
    employees_by_id = {
        employee.id: employee
        for employee in sorted(
            request.employees,
            key=lambda item: (str(item.id), item.name, item.external_id),
        )
    }
    for employee in employees_by_id.values():
        for work_date in month_dates(request.period.year, request.period.month):
            attendance_record = attendance_by_day.get((employee.id, work_date))
            daily_tasks = tasks_by_day.get((employee.id, work_date), {})
            schedule = schedule_by_day.get((employee.id, work_date))
            holiday = holiday_by_day.get(work_date)
            is_holiday, remarks = day_status(employee.role, work_date.weekday(), holiday, schedule)
            activity = _activity(employee.role, work_date.weekday(), is_holiday, request.options)
            rows.append(
                Timesheet(
                    daily_key("timesheet", work_date, employee.id),
                    employee.id,
                    work_date,
                    f"{request.period.year:04d}-{request.period.month:02d}",
                    activity,
                    request.options.default_project,
                    is_holiday,
                    remarks,
                    attendance_record.key if attendance_record is not None else None,
                    tuple(task.key for task in daily_tasks.values()),
                    RecordOrigin.PIPELINE,
                )
            )
    return tuple(rows)


def day_status(
    role: EmployeeRole,
    weekday: int,
    holiday: Holiday | None,
    schedule: Schedule | None,
) -> tuple[bool, str]:
    match role:
        case EmployeeRole.IOT_OPERATIONS:
            if schedule is None or schedule.shift_name is None:
                return True, "OFF"
            shift_name = schedule.shift_name.strip()
            return "libur" in shift_name.casefold(), shift_name or "OFF"
        case EmployeeRole.DEVELOPER:
            if holiday is not None:
                return True, holiday.name
            if weekday >= WEEKEND_START:
                return True, "Weekend"
            return False, "Working Day"
        case _:
            assert_never(role)


def _activity(
    role: EmployeeRole,
    weekday: int,
    is_holiday: bool,
    options: TimesheetOptions,
) -> str:
    if is_holiday:
        return ""
    match role:
        case EmployeeRole.IOT_OPERATIONS:
            return options.iot_activity
        case EmployeeRole.DEVELOPER:
            return (
                options.weekend_activity if weekday >= WEEKEND_START else options.weekday_activity
            )
        case _:
            assert_never(role)
