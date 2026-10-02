from __future__ import annotations

from datetime import date

from digital_bast.domain.completion import (
    CheckState,
    DateRange,
    EmployeeFacts,
    TaskFact,
    TimesheetFact,
    evaluate_employee,
)

_DAY = date(2026, 9, 10)
_PERIOD = DateRange(_DAY, _DAY)


def _facts(task: TaskFact) -> EmployeeFacts:
    return EmployeeFacts(
        employee_id="EMP-1",
        name="Talent One",
        off_days=frozenset({_DAY}),
        attendance=(),
        timesheets=(TimesheetFact(work_date=_DAY, remarks="OFF"),),
        tasks=(task,),
        evidence_available=True,
        attendance_available=True,
    )


def test_closed_task_without_requirement_does_not_need_evidence() -> None:
    result = evaluate_employee(
        _facts(
            TaskFact(
                work_date=_DAY,
                title="Monitoring Dashboard",
                status="Closed",
                evidence_count=0,
                evidence_required=False,
            )
        ),
        _PERIOD,
    )

    assert result.task_list.state is CheckState.COMPLETE
    assert result.evidence.state is CheckState.COMPLETE
    assert result.evidence.issues == ()


def test_closed_required_task_without_evidence_is_blocker() -> None:
    result = evaluate_employee(
        _facts(
            TaskFact(
                work_date=_DAY,
                title="Production Deployment",
                status="Closed",
                evidence_count=0,
                evidence_required=True,
            )
        ),
        _PERIOD,
    )

    assert result.evidence.state is CheckState.INCOMPLETE
    assert result.evidence.issues == ('Task "Production Deployment" belum ada evidence.',)


def test_open_task_remains_task_blocker_even_when_evidence_not_required() -> None:
    result = evaluate_employee(
        _facts(
            TaskFact(
                work_date=_DAY,
                title="API Integration",
                status="In Progress",
                evidence_count=0,
                evidence_required=False,
            )
        ),
        _PERIOD,
    )

    assert result.task_list.state is CheckState.INCOMPLETE
    assert result.task_list.issues == ('Task "API Integration" belum Closed.',)
    assert result.evidence.state is CheckState.COMPLETE
