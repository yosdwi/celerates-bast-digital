from __future__ import annotations

from datetime import date  # noqa: TC003 - Pydantic resolves this type at runtime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from digital_bast.web.payroll_contracts import (
    PayrollCycleResponse,
    PayrollDigestSummaryResponse,
    PayrollFollowUpItemResponse,
)


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)


class PayrollClosingQueryInput(_FrozenModel):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]
    role: Literal["Developer", "IoT Operations"] | None = None


class PayrollClosingQueryResponse(_FrozenModel):
    status: Literal["ok", "unavailable"]
    answer: str | None
    role_filter: Literal["Developer", "IoT Operations"] | None
    cycle: PayrollCycleResponse
    evaluated_through: date | None
    summary: PayrollDigestSummaryResponse
    items: tuple[PayrollFollowUpItemResponse, ...]
