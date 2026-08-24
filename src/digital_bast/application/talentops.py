from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.domain.completion import CheckState, evaluate_completion
from digital_bast.domain.models import EmployeeRole, EntityKind, Month, Task

if TYPE_CHECKING:
    from collections.abc import Callable

    from digital_bast.application.ports import DomainRepository
    from digital_bast.domain.completion import (
        CheckResult,
        DateRange,
        EmployeeCompletion,
        EmployeeFacts,
    )
    from digital_bast.domain.models import Employee

_SOURCE_LABELS = {
    "attendance": "PAMA Attendance",
    "redmine": "Redmine",
    "iot_sheet": "IoT task source",
}
_SOURCE_ORDER = ("attendance", "redmine", "iot_sheet")


class CompletionFactsSource(Protocol):
    async def load(
        self,
        period: DateRange,
        employee: str | None = None,
    ) -> tuple[EmployeeFacts, ...]: ...


class RosterSource(Protocol):
    async def load(self) -> tuple[Employee, ...]: ...


@dataclass(frozen=True, slots=True)
class SourceSyncSnapshot:
    source_key: str
    last_success_at: datetime


class SourceSyncStateReader(Protocol):
    async def load(self) -> tuple[SourceSyncSnapshot, ...]: ...


@dataclass(frozen=True, slots=True)
class PeriodView:
    year: int
    month: int
    start: str
    end: str
    label: str


@dataclass(frozen=True, slots=True)
class CommandCenterSummary:
    active_talents: int
    bast_ready: int
    need_attention: int
    open_tasks: int
    evidence_ready: int


@dataclass(frozen=True, slots=True)
class CheckSummary:
    state: CheckState
    issue_count: int


@dataclass(frozen=True, slots=True)
class ReadinessChecks:
    attendance: CheckSummary
    timesheet: CheckSummary
    task: CheckSummary
    evidence: CheckSummary


@dataclass(frozen=True, slots=True)
class Blocker:
    domain: str
    state: CheckState
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TalentReadiness:
    employee_id: str
    nrp: str
    name: str
    role: EmployeeRole
    overall_state: CheckState
    checks: ReadinessChecks


@dataclass(frozen=True, slots=True)
class AttentionItem:
    employee_id: str
    nrp: str
    name: str
    role: EmployeeRole
    overall_state: CheckState
    blockers: tuple[Blocker, ...]


@dataclass(frozen=True, slots=True)
class TeamCheckCounts:
    attendance_ready: int
    timesheet_ready: int
    task_ready: int
    evidence_ready: int


@dataclass(frozen=True, slots=True)
class TeamReadiness:
    role: EmployeeRole
    total: int
    ready: int
    checks: TeamCheckCounts


@dataclass(frozen=True, slots=True)
class TaskStatusCount:
    status: str
    count: int


@dataclass(frozen=True, slots=True)
class DeliverySummary:
    total_tasks: int
    closed_tasks: int
    non_closed_tasks: int
    status_counts: tuple[TaskStatusCount, ...]


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    source_key: str
    label: str
    last_success_at: datetime | None
    age_seconds: int | None


@dataclass(frozen=True, slots=True)
class CommandCenterView:
    period: PeriodView
    summary: CommandCenterSummary
    attention: tuple[AttentionItem, ...]
    readiness: tuple[TalentReadiness, ...]
    teams: tuple[TeamReadiness, ...]
    delivery: DeliverySummary
    sources: tuple[SourceFreshness, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _summary(result: CheckResult) -> CheckSummary:
    return CheckSummary(state=result.state, issue_count=len(result.issues))


def _checks(completion: EmployeeCompletion) -> ReadinessChecks:
    return ReadinessChecks(
        attendance=_summary(completion.log_1_pama),
        timesheet=_summary(completion.timesheet),
        task=_summary(completion.task_list),
        evidence=_summary(completion.evidence),
    )


def _blockers(completion: EmployeeCompletion) -> tuple[Blocker, ...]:
    ordered = (
        ("attendance", completion.log_1_pama),
        ("timesheet", completion.timesheet),
        ("task", completion.task_list),
        ("evidence", completion.evidence),
    )
    return tuple(
        Blocker(domain=domain, state=result.state, issues=result.issues)
        for domain, result in ordered
        if result.state is not CheckState.COMPLETE
    )


def _status_counts(tasks: tuple[Task, ...]) -> tuple[TaskStatusCount, ...]:
    counts: dict[str, tuple[str, int]] = {}
    for task in tasks:
        display = task.status.strip() or "Unknown"
        key = display.casefold()
        previous = counts.get(key)
        counts[key] = (display, 1 if previous is None else previous[1] + 1)
    return tuple(
        TaskStatusCount(status=display, count=count)
        for display, count in sorted(
            counts.values(),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    )


@final
class TalentOpsService:
    def __init__(
        self,
        completion: CompletionFactsSource,
        employees: RosterSource,
        records: DomainRepository,
        source_sync: SourceSyncStateReader,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._completion = completion
        self._employees = employees
        self._records = records
        self._source_sync = source_sync
        self._now = now

    async def command_center(self, period: DateRange) -> CommandCenterView:
        roster = await self._employees.load()
        completion = evaluate_completion(period, await self._completion.load(period))
        roster_by_id = {str(person.id): person for person in roster}
        readiness = tuple(
            self._talent_readiness(item, roster_by_id[item.employee_id])
            for item in completion.employees
        )
        attention = tuple(
            self._attention_item(item, roster_by_id[item.employee_id])
            for item in completion.employees
            if item.state is not CheckState.COMPLETE
        )
        tasks = await self._tasks(period)
        delivery = DeliverySummary(
            total_tasks=len(tasks),
            closed_tasks=sum(
                task.status.strip().casefold() == "closed"
                for task in tasks
            ),
            non_closed_tasks=sum(
                task.status.strip().casefold() != "closed"
                for task in tasks
            ),
            status_counts=_status_counts(tasks),
        )
        summary = CommandCenterSummary(
            active_talents=len(roster),
            bast_ready=sum(
                item.overall_state is CheckState.COMPLETE
                for item in readiness
            ),
            need_attention=len(attention),
            open_tasks=delivery.non_closed_tasks,
            evidence_ready=sum(
                item.checks.evidence.state is CheckState.COMPLETE
                for item in readiness
            ),
        )
        return CommandCenterView(
            period=PeriodView(
                year=period.start.year,
                month=period.start.month,
                start=period.start.isoformat(),
                end=period.end.isoformat(),
                label=period.label(),
            ),
            summary=summary,
            attention=attention,
            readiness=readiness,
            teams=self._teams(readiness),
            delivery=delivery,
            sources=await self._sources(),
        )

    @staticmethod
    def _talent_readiness(
        completion: EmployeeCompletion,
        person: Employee,
    ) -> TalentReadiness:
        return TalentReadiness(
            employee_id=completion.employee_id,
            nrp=person.external_id,
            name=completion.name,
            role=person.role,
            overall_state=completion.state,
            checks=_checks(completion),
        )

    @staticmethod
    def _attention_item(
        completion: EmployeeCompletion,
        person: Employee,
    ) -> AttentionItem:
        return AttentionItem(
            employee_id=completion.employee_id,
            nrp=person.external_id,
            name=completion.name,
            role=person.role,
            overall_state=completion.state,
            blockers=_blockers(completion),
        )

    async def _tasks(self, period: DateRange) -> tuple[Task, ...]:
        tasks: list[Task] = []
        for year, month in period.months():
            records = await self._records.list_month(
                EntityKind.TASK,
                Month(year, month),
            )
            tasks.extend(
                record
                for record in records
                if isinstance(record, Task)
                and period.start <= record.work_date <= period.end
            )
        return tuple(tasks)

    @staticmethod
    def _teams(readiness: tuple[TalentReadiness, ...]) -> tuple[TeamReadiness, ...]:
        teams: list[TeamReadiness] = []
        for role in EmployeeRole:
            members = tuple(item for item in readiness if item.role is role)
            teams.append(
                TeamReadiness(
                    role=role,
                    total=len(members),
                    ready=sum(
                        item.overall_state is CheckState.COMPLETE
                        for item in members
                    ),
                    checks=TeamCheckCounts(
                        attendance_ready=sum(
                            item.checks.attendance.state is CheckState.COMPLETE
                            for item in members
                        ),
                        timesheet_ready=sum(
                            item.checks.timesheet.state is CheckState.COMPLETE
                            for item in members
                        ),
                        task_ready=sum(
                            item.checks.task.state is CheckState.COMPLETE
                            for item in members
                        ),
                        evidence_ready=sum(
                            item.checks.evidence.state is CheckState.COMPLETE
                            for item in members
                        ),
                    ),
                )
            )
        return tuple(teams)

    async def _sources(self) -> tuple[SourceFreshness, ...]:
        snapshots = {
            item.source_key: item
            for item in await self._source_sync.load()
        }
        now = self._now()
        return tuple(
            self._freshness(source_key, snapshots.get(source_key), now)
            for source_key in _SOURCE_ORDER
        )

    @staticmethod
    def _freshness(
        source_key: str,
        snapshot: SourceSyncSnapshot | None,
        now: datetime,
    ) -> SourceFreshness:
        if snapshot is None:
            return SourceFreshness(
                source_key=source_key,
                label=_SOURCE_LABELS[source_key],
                last_success_at=None,
                age_seconds=None,
            )
        age_seconds = max(
            0,
            int((now - snapshot.last_success_at).total_seconds()),
        )
        return SourceFreshness(
            source_key=source_key,
            label=_SOURCE_LABELS[source_key],
            last_success_at=snapshot.last_success_at,
            age_seconds=age_seconds,
        )
