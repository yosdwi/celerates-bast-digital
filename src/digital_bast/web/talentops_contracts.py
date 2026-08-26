from __future__ import annotations

from datetime import date, datetime  # noqa: TC003
from typing import Annotated, ClassVar, Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from digital_bast.application.operational_signals import OperationalSignalKind  # noqa: TC001
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


class OperationalSignalResponse(_FrozenModel):
    kind: OperationalSignalKind
    title: str
    summary: str
    domains: tuple[str, ...] = ()
    dates: tuple[date, ...] = ()
    task_titles: tuple[str, ...] = ()
    nrp: str | None = None
    role: EmployeeRole | None = None


class CommandCenterResponse(_FrozenModel):
    period: PeriodResponse
    summary: CommandCenterSummaryResponse
    attention: tuple[AttentionItemResponse, ...]
    readiness: tuple[TalentReadinessResponse, ...]
    teams: tuple[TeamReadinessResponse, ...]
    delivery: DeliverySummaryResponse
    sources: tuple[SourceFreshnessResponse, ...]
    signals: tuple[OperationalSignalResponse, ...] = ()


class AttendanceDayResponse(_FrozenModel):
    work_date: date
    is_off: bool
    has_record: bool
    has_clock_in: bool
    has_clock_out: bool
    has_evidence: bool
    state: CheckState


class TimesheetDayResponse(_FrozenModel):
    work_date: date
    is_off: bool
    has_record: bool
    has_remarks: bool
    blocked_by_attendance: bool
    state: CheckState


class TalentTaskResponse(_FrozenModel):
    work_date: date
    title: str
    status: str
    evidence_count: int
    is_closed: bool
    evidence_ready: bool | None


class TalentDataAvailabilityResponse(_FrozenModel):
    attendance: bool
    evidence: bool


class TalentDetailResponse(_FrozenModel):
    period: PeriodResponse
    nrp: str
    name: str
    role: EmployeeRole
    overall_state: CheckState
    checks: ReadinessChecksResponse
    blockers: tuple[BlockerResponse, ...]
    attendance_days: tuple[AttendanceDayResponse, ...]
    timesheet_days: tuple[TimesheetDayResponse, ...]
    tasks: tuple[TalentTaskResponse, ...]
    availability: TalentDataAvailabilityResponse
    signals: tuple[OperationalSignalResponse, ...] = ()


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


class FollowUpDraftInput(_FrozenModel):
    year: int | None = Field(default=None, ge=2020, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)


class FollowUpRecordResponse(_FrozenModel):
    id: str
    source: str
    status: str
    created_by: str
    created_at: datetime
    sent_at: datetime | None


class FollowUpDraftResponse(_FrozenModel):
    nrp: str
    name: str
    whatsapp_bound: bool
    message: str
    source: Literal["deterministic", "ai", "edited"]
    last_follow_up: FollowUpRecordResponse | None


class FollowUpSendInput(_FrozenModel):
    year: int | None = Field(default=None, ge=2020, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    idempotency_key: UUID
    source: Literal["deterministic", "ai", "edited"] = "edited"
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
    ]


class FollowUpSendResponse(_FrozenModel):
    status: Literal[
        "sent",
        "not_bound",
        "bridge_unavailable",
        "failed",
        "no_blockers",
    ]
    delivery_id: str | None
    provider_message_id: str | None
    sent_at: datetime | None
    error_code: str | None
    duplicate: bool = False
