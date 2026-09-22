"""Add a canonical all-status Task List section to assembled BAST output.

Legacy BAST detail sections contain role-specific calculations and historically
filter to Closed tasks. Rather than weakening those calculations, this module
adds a bounded canonical table that prints every task status for the selected
role and month. Readiness rules remain separate and still require Closed.
"""

from __future__ import annotations

import hashlib
import html
import json
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.web.bast_assembler import AssembledReport

_ITEMS_PER_PAGE = 18
_ROLE_BY_REPORT = {"developer": "Developer", "shifting": "IoT Operations"}
_DOCUMENT_MARKER = "    <!-- Document Footer -->"
_EDITOR_MARKER = (
    '    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/'
    'dist/js/bootstrap.bundle.min.js"></script>'
)


@dataclass(frozen=True, slots=True)
class _TaskStatusRow:
    nrp: str
    name: str
    work_date: date
    title: str
    status: str
    source: str


class _TaskRow:
    __slots__ = ("name", "nrp", "source", "status", "title", "work_date")

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors selected task row
        self,
        nrp: str | None,
        name: str | None,
        work_date: date,
        title: str | None,
        status: str | None,
        source: str,
    ) -> None:
        self.nrp = nrp or "-"
        self.name = name or "Unassigned"
        self.work_date = work_date
        self.title = title or ""
        self.status = status or "Unknown"
        self.source = source


@final
class AllStatusTaskSectionService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def rows(
        self,
        report_type: str,
        year: int,
        month: int,
    ) -> tuple[_TaskStatusRow, ...]:
        return await run_sync(self._rows, report_type, year, month)

    def _rows(
        self,
        report_type: str,
        year: int,
        month: int,
    ) -> tuple[_TaskStatusRow, ...]:
        role = _ROLE_BY_REPORT.get(report_type)
        if role is None:
            return ()
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor(row_factory=class_row(_TaskRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT e.nrp,
                           e.full_name AS name,
                           t.work_date,
                           t.title,
                           t.status,
                           t.task_source AS source
                    FROM tasks t
                    LEFT JOIN employees e ON e.employee_id = t.employee_id
                    WHERE t.work_date BETWEEN %s AND %s
                      AND e.role = %s
                    ORDER BY t.work_date, e.full_name, t.record_key
                    """,
                    (start, end, role),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="bast_all_status_tasks",
            ) from error
        return tuple(
            _TaskStatusRow(
                nrp=row.nrp,
                name=row.name,
                work_date=row.work_date,
                title=row.title,
                status=row.status,
                source=row.source,
            )
            for row in rows
        )


def _table(rows: tuple[_TaskStatusRow, ...]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{index}</td>"
        f"<td>{html.escape(item.work_date.strftime('%d/%m/%Y'))}</td>"
        f"<td>{html.escape(item.title)}</td>"
        f"<td>{html.escape(item.status)}</td>"
        f"<td>{html.escape(item.name)}</td>"
        f"<td>{html.escape(item.nrp)}</td>"
        f"<td>{html.escape(item.source)}</td>"
        "</tr>"
        for index, item in enumerate(rows, start=1)
    )
    return (
        '<div class="bast-all-status-tasks">'
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:Arial,sans-serif;font-size:10px">'
        "<thead><tr>"
        '<th style="border:1px solid #000;padding:5px">No</th>'
        '<th style="border:1px solid #000;padding:5px">Tanggal</th>'
        '<th style="border:1px solid #000;padding:5px">Task</th>'
        '<th style="border:1px solid #000;padding:5px">Status</th>'
        '<th style="border:1px solid #000;padding:5px">PIC</th>'
        '<th style="border:1px solid #000;padding:5px">NRP</th>'
        '<th style="border:1px solid #000;padding:5px">Source</th>'
        "</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _document_pages(rows: tuple[_TaskStatusRow, ...]) -> str:
    pages: list[str] = []
    total = max((len(rows) + _ITEMS_PER_PAGE - 1) // _ITEMS_PER_PAGE, 1)
    for page in range(total):
        chunk = rows[page * _ITEMS_PER_PAGE : (page + 1) * _ITEMS_PER_PAGE]
        suffix = f" — Halaman {page + 1}/{total}" if total > 1 else ""
        pages.append(
            '<div class="page-break">'
            '<div class="page-header"><div class="section-title">'
            f"Task List — All Status{suffix}"
            "</div></div>"
            f'<div class="section-content">{_table(chunk)}</div>'
            "</div>"
        )
    return "\n".join(pages)


def _editor_pages(rows: tuple[_TaskStatusRow, ...]) -> str:
    pages: list[str] = []
    total = max((len(rows) + _ITEMS_PER_PAGE - 1) // _ITEMS_PER_PAGE, 1)
    for page in range(total):
        chunk = rows[page * _ITEMS_PER_PAGE : (page + 1) * _ITEMS_PER_PAGE]
        suffix = f" — Halaman {page + 1}/{total}" if total > 1 else ""
        pages.append(
            '<div class="page portrait tasklist-page">'
            '<div class="page-header"><div class="section-title">'
            f"Task List — All Status{suffix}"
            "</div></div>"
            '<div class="section-container tasklist-container" data-section="tasklist">'
            f"{_table(chunk)}"
            "</div></div>"
        )
    return "\n".join(pages)


def _fingerprint(report: AssembledReport, rows: tuple[_TaskStatusRow, ...]) -> str:
    serialized = json.dumps(
        [
            {
                "nrp": item.nrp,
                "name": item.name,
                "date": item.work_date.isoformat(),
                "title": item.title,
                "status": item.status,
                "source": item.source,
            }
            for item in rows
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    source = f"{report.fingerprint}:all-status:{serialized}"
    return hashlib.sha256(source.encode()).hexdigest()


async def include_all_task_statuses(
    report: AssembledReport,
    dsn: str,
) -> AssembledReport:
    rows = await AllStatusTaskSectionService(dsn).rows(
        report.report_type,
        report.year,
        report.month,
    )
    if not rows:
        return report
    if _DOCUMENT_MARKER not in report.document or _EDITOR_MARKER not in report.editor_html:
        raise InfrastructureError(
            service="bast",
            operation="inject_all_status_task_section",
        )
    document = report.document.replace(
        _DOCUMENT_MARKER,
        f"{_document_pages(rows)}\n{_DOCUMENT_MARKER}",
        1,
    )
    editor = report.editor_html.replace(
        _EDITOR_MARKER,
        f"{_editor_pages(rows)}\n{_EDITOR_MARKER}",
        1,
    )
    return AssembledReport(
        report_type=report.report_type,
        year=report.year,
        month=report.month,
        fingerprint=_fingerprint(report, rows),
        document=document,
        editor_html=editor,
    )
