import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_export import PayrollExportRecord, PayrollExportService


class History:
    def __init__(self) -> None:
        self.items: list[PayrollExportRecord] = []

    async def record(self, item: PayrollExportRecord) -> PayrollExportRecord:
        self.items.append(item)
        return item

    async def list(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 50,
    ) -> tuple[PayrollExportRecord, ...]:
        selected = [item for item in self.items if cycle_id is None or item.cycle_id == cycle_id]
        return tuple(reversed(selected[-limit:]))


def test_payroll_export_wraps_legacy_exporter_with_selected_21_to_20_cycle(tmp_path: Path) -> None:
    calls: list[tuple[object, str, str | None]] = []
    export_path = tmp_path / "Attendance_Celerates_Combined_2026-08-21_to_2026-09-20 (DEVELOPER).csv"
    export_path.write_text("legacy,csv\n", encoding="utf-8")

    async def exporter(period: object, report_type: str, employee: str | None) -> tuple[Path, int]:
        calls.append((period, report_type, employee))
        return export_path, 17

    history = History()
    exported_at = datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    service = PayrollExportService(exporter, history, now=lambda: exported_at)
    cycle = payroll_cycle(2026, 9)

    path, record = asyncio.run(
        service.export(
            cycle,
            report_type="developer",
            exported_by="pmo@example.com",
            employee="  Andi  ",
        )
    )

    period, report_type, employee = calls[0]
    assert period.start.isoformat() == "2026-08-21"
    assert period.end.isoformat() == "2026-09-20"
    assert report_type == "developer"
    assert employee == "Andi"
    assert path == export_path
    assert record.cycle_id == "2026-09:2026-08-21:2026-09-20"
    assert record.cycle_label == "Payroll September 2026"
    assert record.start_date.isoformat() == "2026-08-21"
    assert record.end_date.isoformat() == "2026-09-20"
    assert record.exported_at == exported_at
    assert record.exported_by == "pmo@example.com"
    assert record.role_filter == "Developer"
    assert record.filename == export_path.name
    assert record.result == "SUCCESS"
    assert record.row_count == 17
    assert history.items == [record]


def test_payroll_export_rejects_unknown_report_type_before_exporter() -> None:
    called = False

    async def exporter(period: object, report_type: str, employee: str | None) -> tuple[Path, int]:
        nonlocal called
        called = True
        raise AssertionError((period, report_type, employee))

    service = PayrollExportService(exporter, History())

    with pytest.raises(ValueError, match="unsupported payroll attendance report type"):
        asyncio.run(
            service.export(
                payroll_cycle(2026, 9),
                report_type="unknown",
                exported_by="pmo@example.com",
            )
        )

    assert called is False
