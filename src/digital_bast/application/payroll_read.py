from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.attendance_closing import (
    AttendanceClosingDayInput,
    AttendanceClosingReason,
    AttendanceClosingService,
    AttendanceClosingStatus,
    AttendanceCorrectionState,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import evaluated_through
from digital_bast.domain.completion import resolve_off_days
from digital_bast.domain.models import (
    EmployeeRole,
    EntityKind,
    Holiday,
    Month,
    Schedule,
    Timesheet,
)
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.domain.completion import DateRange
    from digital_bast.domain.models import DomainRecord, Employee


class EmployeeSource(Protocol):
    async def load(self) -> tuple[Employee, ...]: ...


class MonthlyRecordSource(Protocol):
    async def list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class PayrollAttendanceRecord:
    attendance_id: int
    attendance_key: str
    employee_id: str
    work_date: date
    check_in: time | None
    check_out: time | None
    has_evidence: bool
    resolution_id: str | None = None
    resolution_status: str | None = None
    resolution_type: str | None = None
    absence_type: str | None = None
    proposed_check_in: time | None = None
    proposed_check_out: time | None = None
    submitted_at: datetime | None = None
    rejection_reason: str | None = None


class PayrollAttendanceReader(Protocol):
    async def load(self, period: DateRange) -> tuple[PayrollAttendanceRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class PayrollDayView:
    attendance_id: int | None
    attendance_key: str | None
    work_date: date
    schedule_state: AttendanceScheduleState
    source_state: AttendanceSourceState
    raw_check_in: str | None
    raw_check_out: str | None
    proposed_check_in: str | None
    proposed_check_out: str | None
    resolution_id: str | None
    resolution_status: str | None
    resolution_type: str | None
    absence_type: str | None
    rejection_reason: str | None
    has_evidence: bool
    status: AttendanceClosingStatus
    reason: AttendanceClosingReason
    talent_action_required: bool


@dataclass(frozen=True, slots=True)
class PayrollTalentView:
    employee_id: str
    nrp: str
    name: str
    role: str
    status: AttendanceClosingStatus
    evaluated_days: int
    complete_days: int
    waiting_days: int
    actionable_days: int
    unverified_days: int
    days: tuple[PayrollDayView, ...]

    @property
    def talent_action_required(self) -> bool:
        return self.actionable_days > 0


@dataclass(frozen=True, slots=True)
class PayrollSummary:
    total_talents: int
    complete: int
    waiting_submitted: int
    needs_talent_action: int
    unverified: int


@dataclass(frozen=True, slots=True)
class PayrollOverview:
    cycle: PayrollCycle
    evaluated_through: date | None
    summary: PayrollSummary
    talents: tuple[PayrollTalentView, ...]


def closing_evaluated_through(
    cycle: PayrollCycle,
    now: datetime,
    *,
    next_day_ready_hour: int = 6,
) -> date | None:
    """Return the latest day whose configured next-day evaluation window ended."""
    if not 0 <= next_day_ready_hour <= 23:  # noqa: PLR2004 - valid clock-hour bound
        msg = "next_day_ready_hour must be between 0 and 23"
        raise ValueError(msg)

    def ready_at(work_date: date) -> datetime:
        return datetime.combine(
            work_date + timedelta(days=1),
            time(next_day_ready_hour),
            JAKARTA,
        )

    return evaluated_through(cycle, now, ready_at)


def _clock(value: time | None) -> str | None:
    return None if value is None else value.strftime("%H:%M")


def _correction_state(value: str | None) -> AttendanceCorrectionState:
    return {
        None: AttendanceCorrectionState.NONE,
        "pending": AttendanceCorrectionState.SUBMITTED,
        "approved": AttendanceCorrectionState.APPROVED,
        "rejected": AttendanceCorrectionState.REJECTED,
    }.get(value, AttendanceCorrectionState.NONE)


def _coverage(resolution_type: str | None) -> tuple[bool, bool]:
    if resolution_type == "missing_clock_in":
        return True, False
    if resolution_type == "missing_clock_out":
        return False, True
    if resolution_type in {"missing_both_worked", "absence"}:
        return True, True
    return False, False


def _verified_off_days(
    employee: Employee,
    cycle: PayrollCycle,
    holidays: dict[date, Holiday],
    schedules: dict[date, Schedule],
    timesheets: dict[date, Timesheet],
) -> frozenset[date]:
    resolved = set(
        resolve_off_days(
            employee.role,
            cycle.period,
            holidays,
            schedules,
            timesheets,
        )
    )
    if employee.role is EmployeeRole.IOT_OPERATIONS:
        # Missing schedule + missing timesheet is source ambiguity, not proof of OFF.
        # The legacy resolver defaults a schedule-less IoT day to OFF; Payroll must
        # fail closed instead so source-sync failures never look complete.
        for work_date in cycle.period.days():
            if work_date not in schedules and work_date not in timesheets:
                resolved.discard(work_date)
    return frozenset(resolved)


@final
class PayrollReadService:
    def __init__(
        self,
        employees: EmployeeSource,
        records: MonthlyRecordSource,
        attendance: PayrollAttendanceReader,
        closing: AttendanceClosingService | None = None,
    ) -> None:
        self._employees = employees
        self._records = records
        self._attendance = attendance
        self._closing = closing or AttendanceClosingService()

    async def overview(
        self,
        cycle: PayrollCycle,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
    ) -> PayrollOverview:
        employees = await self._employees.load()
        attendance = await self._attendance.load(cycle.period)
        holidays, schedules, timesheets = await self._calendar(cycle.period)
        boundary = closing_evaluated_through(
            cycle,
            now,
            next_day_ready_hour=next_day_ready_hour,
        )

        attendance_by_employee_day = {
            (row.employee_id, row.work_date): row for row in attendance
        }
        holiday_by_day = {row.work_date: row for row in holidays}
        talents: list[PayrollTalentView] = []
        for employee in employees:
            schedule_by_day = {
                row.work_date: row for row in schedules if row.employee_id == employee.id
            }
            timesheet_by_day = {
                row.work_date: row for row in timesheets if row.employee_id == employee.id
            }
            off_days = _verified_off_days(
                employee,
                cycle,
                holiday_by_day,
                schedule_by_day,
                timesheet_by_day,
            )
            talents.append(
                self._project_employee(
                    employee,
                    cycle,
                    boundary,
                    off_days,
                    attendance_by_employee_day,
                )
            )

        ordered = tuple(
            sorted(talents, key=lambda item: (item.name.casefold(), item.employee_id))
        )
        summary = PayrollSummary(
            total_talents=len(ordered),
            complete=sum(
                item.actionable_days == 0
                and item.waiting_days == 0
                and item.unverified_days == 0
                for item in ordered
            ),
            waiting_submitted=sum(
                item.actionable_days == 0
                and item.waiting_days > 0
                and item.unverified_days == 0
                for item in ordered
            ),
            needs_talent_action=sum(item.actionable_days > 0 for item in ordered),
            unverified=sum(item.unverified_days > 0 for item in ordered),
        )
        return PayrollOverview(cycle, boundary, summary, ordered)

    async def _calendar(
        self,
        period: DateRange,
    ) -> tuple[tuple[Holiday, ...], tuple[Schedule, ...], tuple[Timesheet, ...]]:
        holidays: list[Holiday] = []
        schedules: list[Schedule] = []
        timesheets: list[Timesheet] = []
        for year, month in period.months():
            for kind in (EntityKind.HOLIDAY, EntityKind.SCHEDULE, EntityKind.TIMESHEET):
                for row in await self._records.list_month(kind, Month(year, month)):
                    if not period.start <= row.work_date <= period.end:
                        continue
                    if isinstance(row, Holiday):
                        holidays.append(row)
                    elif isinstance(row, Schedule):
                        schedules.append(row)
                    elif isinstance(row, Timesheet):
                        timesheets.append(row)
        return tuple(holidays), tuple(schedules), tuple(timesheets)

    def _project_employee(
        self,
        employee: Employee,
        cycle: PayrollCycle,
        boundary: date | None,
        off_days: frozenset[date],
        attendance: dict[tuple[str, date], PayrollAttendanceRecord],
    ) -> PayrollTalentView:
        if boundary is None or boundary < cycle.period.start:
            return PayrollTalentView(
                employee_id=str(employee.id),
                nrp=employee.external_id,
                name=employee.name,
                role=employee.role.value,
                status=AttendanceClosingStatus.COMPLETE,
                evaluated_days=0,
                complete_days=0,
                waiting_days=0,
                actionable_days=0,
                unverified_days=0,
                days=(),
            )

        normalized: list[AttendanceClosingDayInput] = []
        source_rows: list[PayrollAttendanceRecord | None] = []
        schedule_states: list[AttendanceScheduleState] = []
        for work_date in cycle.period.days():
            if work_date > boundary:
                break
            source = attendance.get((str(employee.id), work_date))
            is_off = work_date in off_days
            schedule_state = (
                AttendanceScheduleState.OFF if is_off else AttendanceScheduleState.WORKING
            )
            source_state = (
                AttendanceSourceState.AVAILABLE
                if source is not None or is_off
                else AttendanceSourceState.UNAVAILABLE
            )
            covers_in, covers_out = _coverage(source.resolution_type if source else None)
            normalized.append(
                AttendanceClosingDayInput(
                    attendance_id=source.attendance_id if source else None,
                    attendance_date=work_date,
                    clock_in_local=_clock(source.check_in) if source else None,
                    clock_out_local=_clock(source.check_out) if source else None,
                    correction_state=_correction_state(
                        source.resolution_status if source else None
                    ),
                    correction_covers_clock_in=covers_in,
                    correction_covers_clock_out=covers_out,
                    schedule_state=schedule_state,
                    source_state=source_state,
                    has_evidence=source.has_evidence if source else False,
                )
            )
            source_rows.append(source)
            schedule_states.append(schedule_state)

        result = self._closing.evaluate(
            employee_id=str(employee.id),
            rows=normalized,
            evaluated_through=boundary,
        )
        days: list[PayrollDayView] = []
        for detail, source, schedule_state in zip(
            result.days, source_rows, schedule_states, strict=True
        ):
            talent_action_required = (
                detail.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
                and detail.reason is not AttendanceClosingReason.SOURCE_UNAVAILABLE
                and schedule_state is AttendanceScheduleState.WORKING
            )
            days.append(
                PayrollDayView(
                    attendance_id=detail.attendance_id,
                    attendance_key=source.attendance_key if source else None,
                    work_date=detail.attendance_date,
                    schedule_state=schedule_state,
                    source_state=(
                        AttendanceSourceState.AVAILABLE
                        if source is not None or schedule_state is AttendanceScheduleState.OFF
                        else AttendanceSourceState.UNAVAILABLE
                    ),
                    raw_check_in=_clock(source.check_in) if source else None,
                    raw_check_out=_clock(source.check_out) if source else None,
                    proposed_check_in=_clock(source.proposed_check_in) if source else None,
                    proposed_check_out=_clock(source.proposed_check_out) if source else None,
                    resolution_id=source.resolution_id if source else None,
                    resolution_status=source.resolution_status if source else None,
                    resolution_type=source.resolution_type if source else None,
                    absence_type=source.absence_type if source else None,
                    rejection_reason=source.rejection_reason if source else None,
                    has_evidence=source.has_evidence if source else False,
                    status=detail.status,
                    reason=detail.reason,
                    talent_action_required=talent_action_required,
                )
            )

        working = [
            day for day in days if day.schedule_state is AttendanceScheduleState.WORKING
        ]
        actionable_days = sum(day.talent_action_required for day in working)
        waiting_days = sum(
            day.status is AttendanceClosingStatus.WAITING_SUBMITTED for day in working
        )
        unverified_days = sum(
            day.reason is AttendanceClosingReason.SOURCE_UNAVAILABLE for day in working
        )
        complete_days = sum(
            day.status is AttendanceClosingStatus.COMPLETE for day in working
        )
        if actionable_days > 0 or unverified_days > 0:
            status = AttendanceClosingStatus.NEEDS_TALENT_ACTION
        elif waiting_days > 0:
            status = AttendanceClosingStatus.WAITING_SUBMITTED
        else:
            status = AttendanceClosingStatus.COMPLETE

        return PayrollTalentView(
            employee_id=str(employee.id),
            nrp=employee.external_id,
            name=employee.name,
            role=employee.role.value,
            status=status,
            evaluated_days=len(working),
            complete_days=complete_days,
            waiting_days=waiting_days,
            actionable_days=actionable_days,
            unverified_days=unverified_days,
            days=tuple(days),
        )
