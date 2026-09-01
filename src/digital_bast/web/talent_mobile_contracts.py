from __future__ import annotations

from datetime import date  # noqa: TC003 - Pydantic resolves this type at runtime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TalentMobilePeriod(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    month: int
    label: str


class TalentMobileTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_key: str
    title: str
    work_date: date
    task_source: str
    evidence_count: int
    staged_count: int
    complete: bool


class TalentMobileTaskSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    closed: int
    complete: int
    missing: int
    staged: int
    items: tuple[TalentMobileTask, ...]


class TalentMobileAttendanceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    attendance_key: str
    work_date: date
    check_in: str | None
    check_out: str | None
    gap: Literal["missing_clock_in", "missing_clock_out", "missing_both"]
    evidence_count: int


class TalentMobileAttendanceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    work_date: date
    status: Literal["pending", "approved", "rejected"]
    label: str
    rejection_reason: str | None


class TalentMobileAttendanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_work_days: int
    needs_action: int
    missing_data_days: tuple[date, ...]
    items: tuple[TalentMobileAttendanceItem, ...]
    requests: tuple[TalentMobileAttendanceRequest, ...]


class TalentMobileOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    period: TalentMobilePeriod
    task: TalentMobileTaskSummary
    attendance: TalentMobileAttendanceSummary


class TalentMobileMutationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["stored", "staged", "submitted", "already_present", "already_open"]
    message: str
