from dataclasses import dataclass
from datetime import date

from digital_bast.domain.identity import daily_key, holiday_key
from digital_bast.domain.models import (
    Employee,
    EmployeeRole,
    Holiday,
    Month,
    RecordOrigin,
    Schedule,
)
from digital_bast.domain.time import month_dates


@dataclass(frozen=True, slots=True)
class HolidayInput:
    work_date: date
    name: str


def transform_holiday(value: HolidayInput) -> Holiday:
    return Holiday(holiday_key(value.work_date), value.work_date, value.name.strip())


def generate_iot_schedules(
    employees: tuple[Employee, ...],
    period: Month,
) -> tuple[Schedule, ...]:
    employees_by_id = {
        employee.id: employee
        for employee in sorted(
            employees,
            key=lambda item: (str(item.id), item.name, item.external_id),
        )
    }
    return tuple(
        Schedule(
            daily_key("schedule", work_date, employee.id),
            employee.id,
            work_date,
            None,
            RecordOrigin.PIPELINE,
        )
        for employee in employees_by_id.values()
        if employee.role is EmployeeRole.IOT_OPERATIONS
        for work_date in month_dates(period.year, period.month)
    )
