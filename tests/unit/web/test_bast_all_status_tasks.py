from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING

from digital_bast.web import bast_all_status_tasks
from digital_bast.web.bast_assembler import AssembledReport

if TYPE_CHECKING:
    import pytest


class _Rows:
    async def rows(self, report_type: str, year: int, month: int) -> tuple[object, ...]:
        assert report_type == "developer"
        assert (year, month) == (2026, 9)
        return (
            SimpleNamespace(
                nrp="1001",
                name="Talent One",
                work_date=date(2026, 9, 1),
                title="API Integration",
                status="Open",
                source="redmine",
            ),
            SimpleNamespace(
                nrp="1001",
                name="Talent One",
                work_date=date(2026, 9, 10),
                title="Monitoring Dashboard",
                status="In Progress",
                source="redmine",
            ),
            SimpleNamespace(
                nrp="1001",
                name="Talent One",
                work_date=date(2026, 9, 20),
                title="Deployment",
                status="Closed",
                source="redmine",
            ),
        )


def _report() -> AssembledReport:
    return AssembledReport(
        report_type="developer",
        year=2026,
        month=9,
        fingerprint="before",
        document="<html>\n    <!-- Document Footer -->\n</html>",
        editor_html=(
            "<html>\n"
            '    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>\n'
            "</html>"
        ),
    )


async def test_all_status_section_prints_open_progress_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bast_all_status_tasks, "AllStatusTaskSectionService", lambda _dsn: _Rows())

    result = await bast_all_status_tasks.include_all_task_statuses(_report(), "postgres://ignored")

    for status in ("Open", "In Progress", "Closed"):
        assert status in result.document
        assert status in result.editor_html
    assert "Task List — All Status" in result.document
    assert result.fingerprint != "before"
