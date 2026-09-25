from datetime import date, datetime, time

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
)
from digital_bast.application.attendance_closing_policy import PayrollCycle
from digital_bast.application.payroll_read import PayrollAttendanceRecord, PayrollReadService
from digital_bast.domain.completion import DateRange
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.domain.time import JAKARTA


class Employees:
    def __init__(self, rows: tuple[Employee, ...]) -> None:
        self.rows = rows

    async def load(self) -> tuple[Employee, ...]:
        return self.rows


class Records:
    async def list_month(self, kind: object, period: object) -> tuple[object, ...]:
        return ()


class Attendance:
    def __init__(self, rows: tuple[PayrollAttendanceRecord, ...]) -> None:
        self.rows = rows

    async def load(self, period: DateRange) -> tuple[PayrollAttendanceRecord, ...]:
        return tuple(
            row for row in self.rows if period.start <= row.work_date <= period.end
        )


def employee(
    employee_id: str,
    nrp: str,
    name: str,
    role: EmployeeRole = EmployeeRole.DEVELOPER,
) -> Employee:
    return Employee(
        id=EmployeeId(employee_id),
        external_id=nrp,
        name=name,
        role=role,
    )


def one_day_cycle(work_date: date) -> PayrollCycle:
    return PayrollCycle(
        label_year=work_date.year,
        label_month=work_date.month,
        closing_day=20,
        period=DateRange(work_date, work_date),
    )


async def test_payroll_overview_projects_current_attendance_and_corrections() -> None:
    work_date = date(2026, 9, 10)
    employees = (
        employee("emp-a", "A01", "Andi"),
        employee("emp-b", "B01", "Budi"),
        employee("emp-c", "C01", "Citra"),
        employee("emp-d", "D01", "Dimas"),
        employee("emp-e", "E01", "Eka"),
    )
    rows = (
        PayrollAttendanceRecord(
            1,
            "attendance:a",
            "emp-a",
            work_date,
            time(8),
            time(17),
            False,
        ),
        PayrollAttendanceRecord(
            2,
            "attendance:b",
            "emp-b",
            work_date,
            time(8),
            None,
            True,
            resolution_id="request-b",
            resolution_status="pending",
            resolution_type="missing_clock_out",
            proposed_check_out=time(17, 40),
        ),
        PayrollAttendanceRecord(
            3,
            "attendance:c",
            "emp-c",
            work_date,
            None,
            time(17),
            True,
        ),
        PayrollAttendanceRecord(
            4,
            "attendance:e",
            "emp-e",
            work_date,
            None,
            None,
            True,
            resolution_id="request-e",
            resolution_status="approved",
            resolution_type="absence",
            absence_type="sakit",
        ),
    )
    service = PayrollReadService(Employees(employees), Records(), Attendance(rows))

    overview = await service.overview(
        one_day_cycle(work_date),
        now=datetime(2026, 9, 11, 7, 0, tzinfo=JAKARTA),
    )

    assert overview.evaluated_through == work_date
    assert overview.summary.total_talents == 5
    assert overview.summary.complete == 2
    assert overview.summary.waiting_submitted == 1
    assert overview.summary.needs_talent_action == 2
    assert overview.summary.unverified == 1

    by_id = {talent.employee_id: talent for talent in overview.talents}
    assert by_id["emp-a"].status is AttendanceClosingStatus.COMPLETE
    assert by_id["emp-b"].status is AttendanceClosingStatus.WAITING_SUBMITTED
    assert by_id["emp-b"].days[0].proposed_check_out == "17:40"
    assert by_id["emp-c"].status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
    assert by_id["emp-c"].actionable_days == 1
    # SOURCE_UNAVAILABLE (no attendance row at all) is a genuine gap the
    # Talent needs to fill, same as any other missing clock-in/out -- it
    # counts as actionable so the reminder flow picks it up, not as a
    # separate "distrust the source" bucket.
    assert by_id["emp-d"].actionable_days == 1
    assert by_id["emp-d"].unverified_days == 1
    assert by_id["emp-d"].days[0].attendance_id is None
    assert by_id["emp-d"].days[0].talent_action_required is True
    assert by_id["emp-d"].days[0].reason is AttendanceClosingReason.SOURCE_UNAVAILABLE
    assert by_id["emp-e"].status is AttendanceClosingStatus.COMPLETE
    assert (
        by_id["emp-e"].days[0].reason
        is AttendanceClosingReason.GAP_COVERED_BY_APPROVED_CORRECTION
    )


async def test_developer_weekend_without_attendance_is_valid_off_day() -> None:
    saturday = date(2026, 9, 12)
    service = PayrollReadService(
        Employees((employee("emp-a", "A01", "Andi"),)),
        Records(),
        Attendance(()),
    )

    overview = await service.overview(
        one_day_cycle(saturday),
        now=datetime(2026, 9, 13, 7, 0, tzinfo=JAKARTA),
    )

    talent = overview.talents[0]
    assert talent.status is AttendanceClosingStatus.COMPLETE
    assert talent.evaluated_days == 0
    assert talent.unverified_days == 0
    assert talent.days[0].reason is AttendanceClosingReason.SCHEDULED_OFF


async def test_iot_day_without_schedule_timesheet_or_attendance_is_unverified() -> None:
    work_date = date(2026, 9, 14)
    service = PayrollReadService(
        Employees(
            (
                employee(
                    "emp-iot",
                    "I01",
                    "Ira",
                    EmployeeRole.IOT_OPERATIONS,
                ),
            )
        ),
        Records(),
        Attendance(()),
    )

    overview = await service.overview(
        one_day_cycle(work_date),
        now=datetime(2026, 9, 15, 7, 0, tzinfo=JAKARTA),
    )

    talent = overview.talents[0]
    assert talent.actionable_days == 1
    assert talent.unverified_days == 1
    assert talent.days[0].reason is AttendanceClosingReason.SOURCE_UNAVAILABLE
    assert talent.days[0].talent_action_required is True


async def test_current_day_waits_for_next_day_evaluation_boundary() -> None:
    work_date = date(2026, 9, 10)
    service = PayrollReadService(
        Employees((employee("emp-a", "A01", "Andi"),)),
        Records(),
        Attendance(()),
    )

    overview = await service.overview(
        one_day_cycle(work_date),
        now=datetime(2026, 9, 10, 23, 0, tzinfo=JAKARTA),
    )

    assert overview.evaluated_through is None
    assert overview.talents[0].evaluated_days == 0
    assert overview.talents[0].actionable_days == 0
    assert overview.talents[0].unverified_days == 0
