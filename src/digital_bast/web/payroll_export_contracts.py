from __future__ import annotations

from datetime import date, datetime  # noqa: TC003
from typing import ClassVar, Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)


class PayrollExportInput(BaseModel):
    report_type: Literal["developer", "shifting"]
    employee: str | None = Field(default=None, max_length=200)


class PayrollExportHistoryItemResponse(_FrozenModel):
    export_id: UUID
    cycle_id: str
    cycle_label: str
    start_date: date
    end_date: date
    exported_at: datetime
    exported_by: str
    report_type: str
    role_filter: str
    employee_filter: str | None
    filename: str
    result: str
    row_count: int


class PayrollExportHistoryResponse(_FrozenModel):
    cycle_id: str
    cycle_label: str
    start_date: date
    end_date: date
    items: tuple[PayrollExportHistoryItemResponse, ...]
