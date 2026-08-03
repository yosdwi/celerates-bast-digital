from dataclasses import dataclass
from datetime import date, datetime
from typing import NewType, Protocol

from pydantic import BaseModel, ConfigDict, Field

SessionId = NewType("SessionId", str)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    email: str
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    user: AuthenticatedUser
    csrf_token: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ReportItem:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ReportView:
    title: str
    items: tuple[ReportItem, ...]


@dataclass(frozen=True, slots=True)
class EmployeeOption:
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class AttendanceRow:
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


@dataclass(frozen=True, slots=True)
class GenerationResult:
    success: bool
    plan_id: str
    section_id: int | None = None
    title: str = ""
    content: str = ""
    error: str = ""


class GenerationPlanInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str = Field(pattern="^(iotoperation|developer)$")
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2020, le=2100)


class SectionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(min_length=1, max_length=128)
    section_id: int = Field(ge=0)


class StreamSectionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=1_000_000)
    timestamp: str = Field(default="", max_length=64)


class AttendanceFilterInput(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    start_date: date
    end_date: date
    employee: list[str] = Field(default_factory=list)
    csrf_token: str | None = Field(default=None, alias="_csrf_token")


class AttendanceEmployeeInput(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    employee: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    csrf_token: str | None = Field(default=None, alias="_csrf_token")


class AttendanceExportInput(AttendanceFilterInput):
    role_filter: str = Field(default="", max_length=100)
    export_mode: str = Field(default="combined", pattern="^(separate|combined)$")


class OwnerAuthenticator(Protocol):
    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None: ...

    async def ready(self) -> bool: ...


class SessionStore(Protocol):
    async def create(
        self, session_id: SessionId, record: SessionRecord, ttl_seconds: int
    ) -> None: ...

    async def get(self, session_id: SessionId) -> SessionRecord | None: ...

    async def delete(self, session_id: SessionId) -> None: ...

    async def ready(self) -> bool: ...


class WebBackend(Protocol):
    async def ready(self) -> bool: ...

    async def report(
        self, report_type: str, year: int, month: int, evidence_only: bool
    ) -> ReportView: ...

    async def employees(self) -> tuple[EmployeeOption, ...]: ...

    async def attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]: ...

    async def create_plan(self, request: GenerationPlanInput) -> GenerationResult: ...

    async def generate_section(self, request: SectionInput) -> GenerationResult: ...

    async def bulk_data(self, plan_id: str) -> GenerationResult: ...

    async def store_section(self, request: StreamSectionInput) -> int: ...
