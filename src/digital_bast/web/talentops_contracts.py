from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from digital_bast.domain.completion import CheckState  # noqa: TC001
from digital_bast.domain.models import EmployeeRole  # noqa: TC001


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        from_attributes=True,
    )


class SessionUserResponse(_FrozenModel):
    name: str
    role: str


class TalentOpsSessionResponse(_FrozenModel):
    user: SessionUserResponse
    csrf_token: str
    timezone: str


class PeriodResponse(_FrozenModel):
    year: int
    month: int
    start: str
    end: str
    label: str


class CommandCenterSummaryResponse(_FrozenModel):
    active_talents: int
    bast_ready: int
    need_attention: int
    open_tasks: int
    evidence_ready: int


class CheckSummaryResponse(_FrozenModel):
    state: CheckState
    issue_count: int


class ReadinessChecksResponse(_FrozenModel):
    attendance: CheckSummaryResponse
    timesheet: CheckSummaryResponse
    task: CheckSummaryResponse
    evidence: CheckSummaryResponse


class TalentReadinessResponse(_FrozenModel):
    employee_id: str
    nrp: str
    name: str
    role: EmployeeRole
    overall_state: CheckState
    checks: ReadinessChecksResponse


class BlockerResponse(_FrozenModel):
    domain: str
    state: CheckState
    issues: tuple[str, ...]


class AttentionItemResponse(_FrozenModel):
    employee_id: str
    nrp: str
    name: str
    role: EmployeeRole
    overall_state: CheckState
    blockers: tuple[BlockerResponse, ...]


class TeamCheckCountsResponse(_FrozenModel):
    attendance_ready: int
    timesheet_ready: int
    task_ready: int
    evidence_ready: int


class TeamReadinessResponse(_FrozenModel):
    role: EmployeeRole
    total: int
    ready: int
    checks: TeamCheckCountsResponse


class TaskStatusCountResponse(_FrozenModel):
    status: str
    count: int


class DeliverySummaryResponse(_FrozenModel):
    total_tasks: int
    closed_tasks: int
    non_closed_tasks: int
    status_counts: tuple[TaskStatusCountResponse, ...]


class SourceFreshnessResponse(_FrozenModel):
    source_key: str
    label: str
    last_success_at: datetime | None
    age_seconds: int | None


class CommandCenterResponse(_FrozenModel):
    period: PeriodResponse
    summary: CommandCenterSummaryResponse
    attention: tuple[AttentionItemResponse, ...]
    readiness: tuple[TalentReadinessResponse, ...]
    teams: tuple[TeamReadinessResponse, ...]
    delivery: DeliverySummaryResponse
    sources: tuple[SourceFreshnessResponse, ...]


class AiCommandCenterInput(_FrozenModel):
    year: int | None = Field(default=None, ge=2020, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]


class AiCommandCenterResponse(_FrozenModel):
    status: Literal["ok", "unavailable"]
    answer: str | None
