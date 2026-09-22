from __future__ import annotations

from datetime import date

from digital_bast.domain.completion import (
    CheckState,
    EmployeeFacts,
    TaskFact,
    _evidence,
    _task_list,
)


def _facts(task: TaskFact) -> EmployeeFacts:
    return EmployeeFacts(
        employee_id="EMP-1",
        name="Talent One",
        off_days=frozenset(),
        attendance=(),
        timesheets=(),
        tasks=(task,),
        evidence_available=True,
        attendance_available=True,
    )


def test_closed_task_without_requirement_does_not_need_evidence() -> None:
    facts = _facts(
        TaskFact(
            work_date=date(2026, 9, 10),
            title="Monitoring Dashboard",
            status="Closed",
            evidence_count=0,
            evidence_required=False,
        )
    )

    assert _task_list(facts).state is CheckState.COMPLETE
    assert _evidence(facts).state is CheckState.COMPLETE
    assert _evidence(facts).issues == ()


def test_closed_required_task_without_evidence_is_blocker() -> None:
    facts = _facts(
        TaskFact(
            work_date=date(2026, 9, 10),
            title="Production Deployment",
            status="Closed",
            evidence_count=0,
            evidence_required=True,
        )
    )

    result = _evidence(facts)

    assert result.state is CheckState.INCOMPLETE
    assert result.issues == ('Task "Production Deployment" belum ada evidence.',)


def test_open_task_remains_task_blocker_even_when_evidence_not_required() -> None:
    facts = _facts(
        TaskFact(
            work_date=date(2026, 9, 10),
            title="API Integration",
            status="In Progress",
            evidence_count=0,
            evidence_required=False,
        )
    )

    assert _task_list(facts).state is CheckState.INCOMPLETE
    assert _task_list(facts).issues == ('Task "API Integration" belum Closed.',)
    assert _evidence(facts).state is CheckState.COMPLETE
