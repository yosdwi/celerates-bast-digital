from __future__ import annotations

from datetime import date, datetime  # noqa: TC003
from typing import ClassVar
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)


class TaskEvidenceItemResponse(_FrozenModel):
    id: UUID
    employee_id: str
    nrp: str
    full_name: str
    role: str
    task_id: int
    work_date: date
    task_title: str
    task_source: str
    caption: str
    content_type: str
    byte_size: int
    uploaded_at: datetime
    image_url: str


class TaskEvidencePageResponse(_FrozenModel):
    items: tuple[TaskEvidenceItemResponse, ...]
    total: int
    limit: int
    offset: int
