from datetime import date
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    external_id: str
    work_date: date
    title: str
    status: str
    achievement: str


class EmployeeRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str
    role: str


class AttendanceRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    employee_id: str
    full_name: str
    work_date: date
    shift: str
    schedule_in: str
    schedule_out: str
    attendance_code: str
    check_in: str
    check_out: str
    notes: str


class PlanSection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: int = Field(ge=0)
    title: str
    content: str = ""


class StoredPlan(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    report_type: str
    year: int
    month: int
    sections: tuple[PlanSection, ...]


class PlanRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: UUID
    plan: StoredPlan
