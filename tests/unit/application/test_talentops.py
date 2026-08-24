from datetime import UTC, date, datetime

from digital_bast.application.talentops import SourceSyncSnapshot, TalentOpsService
from digital_bast.domain.completion import DateRange, EmployeeFacts, TaskFact, TimesheetFact
from digital_bast.domain.models import (
    Employee,
    EmployeeId,
    EmployeeRole,
    EntityKind,
    Month,
    RecordKey,
    RecordOrigin,
    Task,
    TaskCategory,
    TaskSource,
)

DAY = date(2026, 8, 1)


class FakeCompletionSource:
    async def load(self, period: DateRange, employee: str | None = None) -> tuple[EmployeeFacts, ...]:
        assert period == DateRange(DAY, DAY)
        assert employee is None
        return (
            EmployeeFacts(
                employee_id="e-ready",
                name="Ready Talent",
                off_days=frozenset({DAY}),
                attendance=(),
                timesheets=(TimesheetFact(DAY, "OFF"),),
                tasks=(TaskFact(DAY, "Closed task", "Closed", 1),),
                evidence_available=True,
                attendance_available=True,
            ),
            EmployeeFacts(
                employee_id="e-blocked",
                name="Blocked Talent",
                off_days=frozenset(),
                attendance=(),
                timesheets=(),
                tasks=(TaskFact(DAY, "Open task", "  In Progress  ", 0),),
                evidence_available=True,
                attendance_available=True,
            ),
        )


class FakeEmployees:
    async def load(self) -> tuple[Employee, ...]:
        return (
            Employee(EmployeeId("e-ready"), "NRP1", "Ready Talent", EmployeeRole.DEVELOPER),
            Employee(
                EmployeeId("e-blocked"),
                "NRP2",
                "Blocked Talent",
                EmployeeRole.IOT_OPERATIONS,
            ),
        )


class FakeRecords:
    async def list_month(self, kind: EntityKind, period: Month) -> tuple[Task, ...]:
        assert kind is EntityKind.TASK
        assert period == Month(2026, 8)
        return (
            _task("task-1", "e-ready", "Closed"),
            _task("task-2", "e-blocked", "  In Progress  "),
        )


class FakeSourceSync:
    async def load(self) -> tuple[SourceSyncSnapshot, ...]:
        return (SourceSyncSnapshot("attendance", datetime(2026, 8, 1, 0, tzinfo=UTC)),)


def _task(key: str, employee_id: str, status: str) -> Task:
    return Task(
        key=RecordKey(key),
        employee_id=EmployeeId(employee_id),
        work_date=DAY,
        title=key,
        requestor="PMO",
        status=status,
        category=TaskCategory.CODE_QUALITY,
        source=TaskSource.REDMINE,
        source_id=key,
        assignee=None,
        start_at=None,
        response_at=None,
        close_at=None,
        end_date=DAY,
        achievement=100,
        origin=RecordOrigin.PIPELINE,
    )


async def test_command_center_uses_shared_completion_and_real_task_states() -> None:
    service = TalentOpsService(
        FakeCompletionSource(),
        FakeEmployees(),
        FakeRecords(),  # type: ignore[arg-type]
        FakeSourceSync(),
        now=lambda: datetime(2026, 8, 1, 0, 2, tzinfo=UTC),
    )

    result = await service.command_center(DateRange(DAY, DAY))

    assert result.summary.active_talents == 2
    assert result.summary.bast_ready == 1
    assert result.summary.need_attention == 1
    assert result.summary.open_tasks == 1
    assert result.summary.evidence_ready == 2
    assert result.attention[0].name == "Blocked Talent"
    assert result.attention[0].blockers[0].domain == "attendance"
    assert result.delivery.closed_tasks == 1
    assert result.delivery.non_closed_tasks == 1
    assert result.sources[0].age_seconds == 120
    assert result.sources[1].last_success_at is None
