from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.flows.models import Operation, Period, StepSummary


@runtime_checkable
class RunContext(Protocol):
    def now(self) -> datetime: ...

    async def execute(self, operation: Operation, period: Period) -> StepSummary: ...


class RunContextFactory(Protocol):
    def __call__(self) -> RunContext: ...
