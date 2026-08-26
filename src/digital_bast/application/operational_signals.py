from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from digital_bast.application.talentops import (
        AttentionItem,
        Blocker,
        TeamReadiness,
        TalentTask,
        TimesheetDay,
    )
    from digital_bast.domain.models import EmployeeRole


class OperationalSignalKind(StrEnum):
    ATTENDANCE_BLOCKS_TIMESHEET = "attendance_blocks_timesheet"
    CLOSED_TASK_MISSING_EVIDENCE = "closed_task_missing_evidence"
    MULTI_DOMAIN_BLOCKER = "multi_domain_blocker"
    TEAM_DOMAIN_GAP = "team_domain_gap"


@dataclass(frozen=True, slots=True)
class OperationalSignal:
    kind: OperationalSignalKind
    title: str
    summary: str
    domains: tuple[str, ...] = ()
    dates: tuple[date, ...] = ()
    task_titles: tuple[str, ...] = ()
    nrp: str | None = None
    role: EmployeeRole | None = None


def talent_signals(
    nrp: str,
    blockers: tuple[Blocker, ...],
    timesheet_days: tuple[TimesheetDay, ...],
    tasks: tuple[TalentTask, ...],
) -> tuple[OperationalSignal, ...]:
    signals: list[OperationalSignal] = []

    blocked_dates = tuple(
        day.work_date
        for day in timesheet_days
        if not day.is_off and day.blocked_by_attendance
    )
    if blocked_dates:
        signals.append(
            OperationalSignal(
                kind=OperationalSignalKind.ATTENDANCE_BLOCKS_TIMESHEET,
                title="Attendance blocks Timesheet",
                summary=(
                    f"{len(blocked_dates)} date(s) require Attendance review before "
                    "Timesheet can complete."
                ),
                domains=("attendance", "timesheet"),
                dates=blocked_dates,
                nrp=nrp,
            )
        )

    missing_evidence = tuple(
        task.title
        for task in tasks
        if task.is_closed and task.evidence_ready is False
    )
    if missing_evidence:
        signals.append(
            OperationalSignal(
                kind=OperationalSignalKind.CLOSED_TASK_MISSING_EVIDENCE,
                title="Closed tasks are missing Evidence",
                summary=(
                    f"{len(missing_evidence)} Closed task(s) still have no Evidence attached."
                ),
                domains=("task", "evidence"),
                task_titles=missing_evidence,
                nrp=nrp,
            )
        )

    active_domains = tuple(blocker.domain for blocker in blockers)
    if len(active_domains) > 1:
        signals.append(
            OperationalSignal(
                kind=OperationalSignalKind.MULTI_DOMAIN_BLOCKER,
                title="Multiple domains block closure",
                summary=f"{len(active_domains)} readiness domains still require review.",
                domains=active_domains,
                nrp=nrp,
            )
        )

    return tuple(signals)


def command_center_signals(
    attention: tuple[AttentionItem, ...],
    teams: tuple[TeamReadiness, ...],
) -> tuple[OperationalSignal, ...]:
    signals: list[OperationalSignal] = []

    for item in attention:
        active_domains = tuple(blocker.domain for blocker in item.blockers)
        if len(active_domains) > 1:
            signals.append(
                OperationalSignal(
                    kind=OperationalSignalKind.MULTI_DOMAIN_BLOCKER,
                    title=f"{item.name} has cross-domain blockers",
                    summary=f"{len(active_domains)} readiness domains require coordinated review.",
                    domains=active_domains,
                    nrp=item.nrp,
                    role=item.role,
                )
            )

    for team in teams:
        if team.total <= 0:
            continue
        counts = {
            "attendance": team.checks.attendance_ready,
            "timesheet": team.checks.timesheet_ready,
            "task": team.checks.task_ready,
            "evidence": team.checks.evidence_ready,
        }
        minimum = min(counts.values())
        maximum = max(counts.values())
        if minimum >= maximum:
            continue
        weakest = tuple(domain for domain, ready in counts.items() if ready == minimum)
        signals.append(
            OperationalSignal(
                kind=OperationalSignalKind.TEAM_DOMAIN_GAP,
                title=f"{team.role.value} has a readiness gap",
                summary=(
                    f"{', '.join(weakest)} is the least-ready domain "
                    f"({minimum}/{team.total} ready)."
                ),
                domains=weakest,
                role=team.role,
            )
        )

    return tuple(signals)
