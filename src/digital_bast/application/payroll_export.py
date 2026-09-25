from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from digital_bast.domain.completion import DateRange

if TYPE_CHECKING:
    from digital_bast.application.attendance_closing_policy import PayrollCycle

PayrollExportFunction = Callable[
    [DateRange, str, str | None],
    Awaitable[tuple[Path, int]],
]

_REPORT_ROLES = {
    "developer": "Developer",
    "shifting": "IoT Operations",
}


@dataclass(frozen=True, slots=True)
class PayrollExportRecord:
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


class PayrollExportHistoryStore(Protocol):
    async def record(self, item: PayrollExportRecord) -> PayrollExportRecord: ...

    async def list(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 50,
    ) -> tuple[PayrollExportRecord, ...]: ...


class PayrollExportService:
    def __init__(
        self,
        exporter: PayrollExportFunction,
        history: PayrollExportHistoryStore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._exporter = exporter
        self._history = history
        self._now = now or (lambda: datetime.now(UTC))

    async def export(
        self,
        cycle: PayrollCycle,
        *,
        report_type: str,
        exported_by: str,
        employee: str | None = None,
    ) -> tuple[Path, PayrollExportRecord]:
        role_filter = _REPORT_ROLES.get(report_type)
        if role_filter is None:
            message = "unsupported payroll attendance report type"
            raise ValueError(message)

        employee_filter = employee.strip() if employee and employee.strip() else None
        path, row_count = await self._exporter(cycle.period, report_type, employee_filter)
        record = PayrollExportRecord(
            export_id=uuid4(),
            cycle_id=cycle.cycle_id,
            cycle_label=cycle.label,
            start_date=cycle.period.start,
            end_date=cycle.period.end,
            exported_at=self._now(),
            exported_by=exported_by,
            report_type=report_type,
            role_filter=role_filter,
            employee_filter=employee_filter,
            filename=path.name,
            result="SUCCESS",
            row_count=row_count,
        )
        saved = await self._history.record(record)
        return path, saved

    async def history(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 50,
    ) -> tuple[PayrollExportRecord, ...]:
        return await self._history.list(cycle_id=cycle_id, limit=limit)
