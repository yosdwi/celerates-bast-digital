from __future__ import annotations

from datetime import date

from digital_bast.domain.completion import (
    AttendanceFact,
    CheckState,
    DateRange,
    EmployeeFacts,
    TaskFact,
    TimesheetFact,
    evaluate_completion,
    evaluate_employee,
    resolve_off_days,
)
from digital_bast.domain.identity import daily_key, holiday_key
from digital_bast.domain.models import EmployeeId, EmployeeRole, Holiday, RecordOrigin, Schedule

PERIOD = DateRange(date(2026, 8, 10), date(2026, 8, 12))
WORK_DAY = date(2026, 8, 10)


def facts(**overrides: object) -> EmployeeFacts:
    base: dict[str, object] = {
        "employee_id": "7",
        "name": "Titin",
        "off_days": frozenset(),
        "attendance": (),
        "timesheets": tuple(TimesheetFact(day, "Shift Pagi") for day in PERIOD.days()),
        "tasks": (TaskFact(WORK_DAY, "CCTV Gate 2", "Closed"),),
        "task_evidence_count": 1,
        "attendance_available": True,
    }
    base.update(overrides)
    return EmployeeFacts(**base)  # type: ignore[arg-type]


def complete_attendance() -> tuple[AttendanceFact, ...]:
    return tuple(
        AttendanceFact(day, has_clock_in=True, has_clock_out=True, has_evidence=False)
        for day in PERIOD.days()
    )


def test_work_day_with_both_clocks_is_complete() -> None:
    result = evaluate_employee(facts(attendance=complete_attendance()), PERIOD)

    assert result.log_1_pama.state is CheckState.COMPLETE
    assert result.state is CheckState.COMPLETE


def test_missing_clock_out_without_evidence_is_incomplete() -> None:
    attendance = (
        AttendanceFact(WORK_DAY, has_clock_in=True, has_clock_out=False, has_evidence=False),
        *complete_attendance()[1:],
    )

    result = evaluate_employee(facts(attendance=attendance), PERIOD)

    assert result.log_1_pama.state is CheckState.INCOMPLETE
    assert result.log_1_pama.issues == (
        "10 Agustus — Clock Out belum terisi dan Evidence Attendance belum tersedia.",
    )


def test_missing_clocks_with_evidence_is_valid_exception() -> None:
    attendance = (
        AttendanceFact(WORK_DAY, has_clock_in=False, has_clock_out=False, has_evidence=True),
        *complete_attendance()[1:],
    )

    result = evaluate_employee(facts(attendance=attendance), PERIOD)

    assert result.log_1_pama.state is CheckState.COMPLETE


def test_work_day_without_attendance_row_is_incomplete() -> None:
    result = evaluate_employee(facts(attendance=complete_attendance()[1:]), PERIOD)

    assert result.log_1_pama.issues == ("10 Agustus — Data attendance belum tersedia.",)


def test_off_day_without_attendance_row_is_valid() -> None:
    result = evaluate_employee(
        facts(off_days=frozenset({WORK_DAY}), attendance=complete_attendance()[1:]),
        PERIOD,
    )

    assert result.log_1_pama.state is CheckState.COMPLETE


def test_unmapped_attendance_requests_review() -> None:
    result = evaluate_employee(facts(attendance_available=False), PERIOD)

    assert result.log_1_pama.state is CheckState.NEEDS_REVIEW
    assert result.state is CheckState.NEEDS_REVIEW


def test_timesheet_cannot_be_complete_when_log_1_pama_is_incomplete() -> None:
    result = evaluate_employee(facts(attendance=complete_attendance()[1:]), PERIOD)

    assert result.timesheet.state is CheckState.INCOMPLETE
    assert result.timesheet.issues == (
        "10 Agustus — Timesheet belum dapat lengkap karena Log 1 PAMA belum valid.",
    )


def test_off_day_timesheet_requires_remarks() -> None:
    timesheets = (TimesheetFact(WORK_DAY, "  "), *tuple(
        TimesheetFact(day, "Shift Pagi") for day in PERIOD.days()[1:]
    ))

    result = evaluate_employee(
        facts(
            off_days=frozenset({WORK_DAY}),
            attendance=complete_attendance()[1:],
            timesheets=timesheets,
        ),
        PERIOD,
    )

    assert result.timesheet.issues == ("10 Agustus — Keterangan OFF pada Timesheet belum terisi.",)


def test_off_day_timesheet_with_remarks_is_valid() -> None:
    result = evaluate_employee(
        facts(off_days=frozenset({WORK_DAY}), attendance=complete_attendance()[1:]),
        PERIOD,
    )

    assert result.timesheet.state is CheckState.COMPLETE


def test_missing_off_day_timesheet_row_is_incomplete() -> None:
    result = evaluate_employee(
        facts(
            off_days=frozenset({WORK_DAY}),
            attendance=complete_attendance()[1:],
            timesheets=tuple(TimesheetFact(day, "Shift Pagi") for day in PERIOD.days()[1:]),
        ),
        PERIOD,
    )

    assert result.timesheet.issues == ("10 Agustus — Timesheet untuk jadwal OFF belum tersedia.",)


def test_missing_working_day_timesheet_row_is_incomplete() -> None:
    result = evaluate_employee(
        facts(
            attendance=complete_attendance(),
            timesheets=tuple(TimesheetFact(day, "Shift Pagi") for day in PERIOD.days()[1:]),
        ),
        PERIOD,
    )

    assert result.timesheet.issues == ("10 Agustus — Timesheet belum tersedia.",)


def test_task_status_is_normalized() -> None:
    tasks = (
        TaskFact(WORK_DAY, "A", " CLOSED "),
        TaskFact(WORK_DAY, "B", "closed"),
        TaskFact(WORK_DAY, "C", "Closed"),
    )

    result = evaluate_employee(facts(attendance=complete_attendance(), tasks=tasks), PERIOD)

    assert result.task_list.state is CheckState.COMPLETE


def test_single_open_task_makes_task_list_incomplete() -> None:
    tasks = (
        TaskFact(WORK_DAY, "CCTV Gate 2", "In Progress"),
        TaskFact(WORK_DAY, "Datalog", "Closed"),
    )

    result = evaluate_employee(facts(attendance=complete_attendance(), tasks=tasks), PERIOD)

    assert result.task_list.state is CheckState.INCOMPLETE
    assert result.task_list.issues == ('Task "CCTV Gate 2" belum Closed.',)


def test_zero_tasks_requests_review() -> None:
    result = evaluate_employee(facts(attendance=complete_attendance(), tasks=()), PERIOD)

    assert result.task_list.state is CheckState.NEEDS_REVIEW
    assert result.task_list.issues == ("Belum ada Task List pada periode.",)


def test_single_task_evidence_completes_evidence_check() -> None:
    result = evaluate_employee(
        facts(attendance=complete_attendance(), task_evidence_count=1), PERIOD
    )

    assert result.evidence.state is CheckState.COMPLETE


def test_missing_task_evidence_is_incomplete() -> None:
    result = evaluate_employee(
        facts(attendance=complete_attendance(), task_evidence_count=0), PERIOD
    )

    assert result.evidence.state is CheckState.INCOMPLETE
    assert result.evidence.issues == ("Evidence Task List belum tersedia.",)


def test_unmapped_task_evidence_requests_review() -> None:
    result = evaluate_employee(
        facts(attendance=complete_attendance(), task_evidence_count=None), PERIOD
    )

    assert result.evidence.state is CheckState.NEEDS_REVIEW


def test_report_state_is_worst_employee_state() -> None:
    report = evaluate_completion(
        PERIOD,
        (
            facts(attendance=complete_attendance()),
            facts(employee_id="8", name="Putra", attendance=complete_attendance(), tasks=()),
        ),
    )

    assert report.state is CheckState.NEEDS_REVIEW
    assert len(report.employees) == 2


def test_iot_schedule_drives_off_days() -> None:
    schedules = {
        WORK_DAY: Schedule(
            daily_key("schedule", WORK_DAY, EmployeeId("7")),
            EmployeeId("7"),
            WORK_DAY,
            "LIBUR",
            RecordOrigin.PIPELINE,
        )
    }

    off_days = resolve_off_days(EmployeeRole.IOT_OPERATIONS, PERIOD, {}, schedules)

    assert off_days == frozenset(PERIOD.days())


def test_developer_off_days_follow_holidays_and_weekend() -> None:
    holiday_date = date(2026, 8, 17)
    period = DateRange(date(2026, 8, 14), holiday_date)
    holidays = {holiday_date: Holiday(holiday_key(holiday_date), holiday_date, "Kemerdekaan")}

    off_days = resolve_off_days(EmployeeRole.DEVELOPER, period, holidays, {})

    assert off_days == frozenset({date(2026, 8, 15), date(2026, 8, 16), holiday_date})


def test_range_label_and_days() -> None:
    assert DateRange(date(2026, 8, 1), date(2026, 8, 31)).label() == "1-31 Agustus 2026"
    assert DateRange(date(2026, 7, 20), date(2026, 8, 18)).label() == (
        "20 Juli 2026 - 18 Agustus 2026"
    )
    assert len(PERIOD.days()) == 3
    assert DateRange(date(2026, 7, 20), date(2026, 8, 18)).months() == ((2026, 7), (2026, 8))
