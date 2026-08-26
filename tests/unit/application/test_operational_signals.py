from datetime import date

from digital_bast.application.operational_signals import (
    OperationalSignalKind,
    command_center_signals,
    talent_signals,
)
from digital_bast.application.talentops import (
    AttentionItem,
    Blocker,
    TalentTask,
    TeamCheckCounts,
    TeamReadiness,
    TimesheetDay,
)
from digital_bast.domain.completion import CheckState
from digital_bast.domain.models import EmployeeRole


def test_talent_signals_capture_cross_domain_dependencies() -> None:
    signals = talent_signals(
        "JIMT24002",
        (
            Blocker("attendance", CheckState.INCOMPLETE, ("Attendance missing",)),
            Blocker("timesheet", CheckState.INCOMPLETE, ("Timesheet blocked",)),
            Blocker("evidence", CheckState.INCOMPLETE, ("Evidence missing",)),
        ),
        (
            TimesheetDay(
                work_date=date(2026, 8, 12),
                is_off=False,
                has_record=False,
                has_remarks=False,
                blocked_by_attendance=True,
                state=CheckState.INCOMPLETE,
            ),
            TimesheetDay(
                work_date=date(2026, 8, 13),
                is_off=False,
                has_record=True,
                has_remarks=True,
                blocked_by_attendance=False,
                state=CheckState.COMPLETE,
            ),
        ),
        (
            TalentTask(
                work_date=date(2026, 8, 10),
                title="Close deployment task",
                status="Closed",
                evidence_count=0,
                is_closed=True,
                evidence_ready=False,
            ),
        ),
    )

    by_kind = {signal.kind: signal for signal in signals}
    attendance_dependency = by_kind[OperationalSignalKind.ATTENDANCE_BLOCKS_TIMESHEET]
    assert attendance_dependency.dates == (date(2026, 8, 12),)
    assert attendance_dependency.domains == ("attendance", "timesheet")

    missing_evidence = by_kind[OperationalSignalKind.CLOSED_TASK_MISSING_EVIDENCE]
    assert missing_evidence.task_titles == ("Close deployment task",)

    multi_domain = by_kind[OperationalSignalKind.MULTI_DOMAIN_BLOCKER]
    assert multi_domain.domains == ("attendance", "timesheet", "evidence")


def test_command_center_signals_are_deterministic_without_priority_scoring() -> None:
    attention = (
        AttentionItem(
            employee_id="employee-1",
            nrp="JIMT24002",
            name="Yoses Dwi Maheswara",
            role=EmployeeRole.DEVELOPER,
            overall_state=CheckState.INCOMPLETE,
            blockers=(
                Blocker("attendance", CheckState.INCOMPLETE, ("Attendance missing",)),
                Blocker("timesheet", CheckState.INCOMPLETE, ("Timesheet blocked",)),
            ),
        ),
    )
    teams = (
        TeamReadiness(
            role=EmployeeRole.DEVELOPER,
            total=4,
            ready=2,
            checks=TeamCheckCounts(
                attendance_ready=2,
                timesheet_ready=2,
                task_ready=4,
                evidence_ready=3,
            ),
        ),
    )

    signals = command_center_signals(attention, teams)

    assert tuple(signal.kind for signal in signals) == (
        OperationalSignalKind.MULTI_DOMAIN_BLOCKER,
        OperationalSignalKind.TEAM_DOMAIN_GAP,
    )
    assert signals[0].nrp == "JIMT24002"
    assert signals[1].domains == ("attendance", "timesheet")
    assert "2/4 ready" in signals[1].summary
