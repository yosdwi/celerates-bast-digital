from __future__ import annotations

from datetime import date, datetime  # noqa: TC003
from typing import ClassVar
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field

from digital_bast.application.attendance_closing import (  # noqa: TC001
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.payroll_digest import PayrollFollowUpReason  # noqa: TC001
from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState  # noqa: TC001
from digital_bast.application.payroll_review import (  # noqa: TC001
    PayrollReviewabilityReason,
    PayrollReviewDecision,
    PayrollReviewItemResultStatus,
)
from digital_bast.bot.attendance_resolution import ResolutionType  # noqa: TC001


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)


class PayrollCycleResponse(_FrozenModel):
    cycle_id: str
    label: str
    year: int
    month: int
    start: date
    end: date


class PayrollCyclesResponse(_FrozenModel):
    current_cycle_id: str
    cycles: tuple[PayrollCycleResponse, ...]


class PayrollSummaryResponse(_FrozenModel):
    total_talents: int
    complete: int
    waiting_submitted: int
    needs_talent_action: int
    unverified: int


class PayrollTalentRowResponse(_FrozenModel):
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
    talent_action_required: bool


class PayrollDayResponse(_FrozenModel):
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


class PayrollOverviewResponse(_FrozenModel):
    cycle: PayrollCycleResponse
    evaluated_through: date | None
    summary: PayrollSummaryResponse
    talents: tuple[PayrollTalentRowResponse, ...]


class PayrollTalentDetailResponse(PayrollTalentRowResponse):
    cycle: PayrollCycleResponse
    evaluated_through: date | None
    days: tuple[PayrollDayResponse, ...]


class PayrollReviewSummaryResponse(_FrozenModel):
    total: int
    reviewable: int
    stale: int
    missing_clock_in: int
    missing_clock_out: int
    missing_both_worked: int
    absence: int


class PayrollReviewItemResponse(_FrozenModel):
    request_id: UUID
    attendance_id: int
    employee_id: str
    nrp: str
    name: str
    role: str
    work_date: date
    resolution_type: ResolutionType
    raw_check_in: str | None
    raw_check_out: str | None
    proposed_check_in: str | None
    proposed_check_out: str | None
    absence_type: str | None
    evidence_id: UUID
    evidence_content_type: str | None
    evidence_byte_size: int | None
    evidence_caption: str
    evidence_uploaded_at: datetime | None
    submitted_at: datetime
    reviewable: bool
    reviewability_reason: PayrollReviewabilityReason | None


class PayrollReviewQueueResponse(_FrozenModel):
    cycle: PayrollCycleResponse
    summary: PayrollReviewSummaryResponse
    items: tuple[PayrollReviewItemResponse, ...]


class PayrollReviewDecisionInput(BaseModel):
    request_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    decision: PayrollReviewDecision
    rejection_reason: str | None = Field(default=None, max_length=500)


class PayrollReviewDecisionItemResponse(_FrozenModel):
    request_id: UUID
    status: PayrollReviewItemResultStatus
    outcome: str


class PayrollReviewDecisionResponse(_FrozenModel):
    requested: int
    succeeded: int
    skipped: int
    failed: int
    items: tuple[PayrollReviewDecisionItemResponse, ...]


class PayrollClosingMilestoneResponse(_FrozenModel):
    label: str
    days_before: int
    work_date: date


class PayrollClosingPreviewResponse(_FrozenModel):
    cycle: PayrollCycleResponse
    milestones: tuple[PayrollClosingMilestoneResponse, ...]
    estimated_actionable_talents: int
    estimated_unverified_talents: int


class PayrollClosingSettingsResponse(_FrozenModel):
    scope_key: str
    enabled: bool
    paused: bool
    closing_day: int
    reminder_hour: int
    reminder_offsets: tuple[int, ...]
    target_roles: tuple[str, ...]
    next_day_ready_hour: int
    desired_version: int
    applied_version: int
    updated_by: str | None
    preview: PayrollClosingPreviewResponse


class PayrollClosingSettingsInput(BaseModel):
    enabled: bool = False
    paused: bool = False
    closing_day: int = Field(default=20, ge=1, le=31)
    reminder_hour: int = Field(default=9, ge=0, le=23)
    reminder_offsets: tuple[int, ...] = Field(default=(5, 3, 1), min_length=1, max_length=10)
    target_roles: tuple[str, ...] = Field(
        default=("Developer", "IoT Operations"),
        min_length=1,
        max_length=10,
    )
    next_day_ready_hour: int = Field(default=6, ge=0, le=23)


class PayrollDigestSummaryResponse(_FrozenModel):
    total_talents: int
    complete: int
    waiting_submitted: int
    needs_talent_action: int
    unverified: int
    successful_reminder_deliveries: int
    successfully_reminded_talents: int
    unresponded_talents: int
    actionable_not_reminded: int
    delivery_retryable_failed: int
    delivery_final_failed: int
    delivery_unknown: int


class PayrollFollowUpItemResponse(_FrozenModel):
    employee_id: str
    nrp: str
    name: str
    role: str
    status: str
    actionable_days: int
    waiting_days: int
    unverified_days: int
    reason: PayrollFollowUpReason
    latest_delivery_state: PayrollDeliveryState | None
    latest_milestone: str | None
    latest_sent_at: datetime | None
    responded_at: datetime | None
    error_code: str | None


class PayrollDigestResponse(_FrozenModel):
    cycle: PayrollCycleResponse
    evaluated_through: date | None
    summary: PayrollDigestSummaryResponse
    items: tuple[PayrollFollowUpItemResponse, ...]


class PayrollManualReminderPreviewResponse(_FrozenModel):
    employee_id: str
    eligible: bool
    outcome: str
    actionable_days: int
    message: str | None


class PayrollManualReminderInput(BaseModel):
    request_id: UUID


class PayrollManualReminderResponse(_FrozenModel):
    employee_id: str
    outcome: str
    sent: bool
