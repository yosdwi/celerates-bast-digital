"""V1-compatible BAST document assembly (docs/bast-e2e-plan.md WP4, §3.8).

Templates under templates/bast/ are copied verbatim from v1-prod. This module
supplies deterministic context builders reading real Postgres data instead of
NocoDB -- parity comes from reusing the same template files, not re-authoring
them.

Three known, documented deviations from a byte-for-byte V1 port:

1. Timesheet hour columns (Start/End/Break/Total/Overtime/Regular Hours) were
   pre-computed fields in V1's NocoDB `timesheet` table with no formula
   anywhere in v1-prod's source (grep of v1-prod/src turns up nothing) --
   likely manual entry or a NocoDB automation that was never version
   controlled. Computed here with a standard, documented formula from real
   Attendance clock times (1h fixed break, 8h regular cap, the rest
   overtime) -- not verified against any original V1 numbers, because none
   exist to verify against.
2. `Detail Aktivitas Dukungan Support` (2.3) has no automated source in V1
   either -- grep of v1-prod/src shows zero code producing that Kategori.
   It was always a manually curated NocoDB category. V2 has no manual-entry
   task path (out of scope for this plan), so this section is always empty
   -- which matches V1's own behaviour for any month nobody hand-entered
   support tasks.
3. IoT `Detail Respon Resolution Time` -- deferred per plan §3.8, explicit
   "data SLA belum tersedia" placeholder.

Isolation: all reads run on one connection with the transaction explicitly
raised to REPEATABLE READ (§3.7), so an import or evidence upload landing
mid-assembly cannot produce a document mixing old tasks with new evidence.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final, final

import psycopg
from anyio.to_thread import run_sync
from jinja2 import Environment, FileSystemLoader, select_autoescape
from psycopg.rows import class_row

from digital_bast.domain.models import EmployeeRole
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from digital_bast.domain.models import Employee

_TEMPLATE_DIR: Final = Path(__file__).resolve().parents[3] / "templates" / "bast"
_ENVIRONMENT: Final = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(("html",)),
)
# all_report_template.html references `datetime` inside an HTML comment (dead
# output, but Jinja still evaluates {{ }} expressions regardless of the
# surrounding HTML syntax) -- inject it so the verbatim template renders
# without needing to touch the copied file.
_ENVIRONMENT.globals["datetime"] = datetime  # type: ignore[assignment]

_BODY_PATTERN: Final = re.compile(r"<body[^>]*>(.*?)</body>", re.DOTALL)
_STYLE_PATTERN: Final = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL)
_CSS_COMMENT_PATTERN: Final = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_RULE_PATTERN: Final = re.compile(r"([^{}]+)\{([^{}]*)\}")

_ITEMS_PER_PAGE: Final = 10
_STANDARD_BREAK_HOURS: Final = 1.0
_STANDARD_WORKDAY_HOURS: Final = 8.0
_MAX_WORK_DESCRIPTIONS: Final = 6
_CLOSED: Final = "closed"

_MONTH_NAMES_ID: Final = (
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

_REPORT_ROLE: Final = {
    "developer": EmployeeRole.DEVELOPER,
    "iotoperation": EmployeeRole.IOT_OPERATIONS,
}

_KUALITAS_KODE: Final = "Detail Aktivitas Kualitas Kode"
_WAKTU_RILIS: Final = "Detail Aktivitas Waktu Rilis Fitur"
_DUKUNGAN_SUPPORT: Final = "Detail Aktivitas Dukungan Support"

# Verbatim from v1-prod fastapi_server.py::_generate_iot_problem_page -- static content,
# never computed from data in V1 either.
_IOT_PROBLEM_DATA: Final = (
    {
        "object": "Aktual Waktu Respon (menit)",
        "formula": "(Tanggal Waktu Respon – Tanggal Problem) x 1440",  # noqa: RUF001
        "keterangan": "-",
    },
    {
        "object": "Aktual Waktu Penyelesaian (menit)",
        "formula": "(Tanggal Waktu Penyelesaian – Tanggal Problem) x 1440",  # noqa: RUF001
        "keterangan": "-",
    },
    {
        "object": "Performance Waktu Respon (%)",
        "formula": "100%+((100%-(Aktual Waktu Respon : 15)",
        "keterangan": [
            "Jika hasil waktu respon >100%, maka hasil maksimal tetap 100%",
            "Jika hasil waktu respon <0%, maka hasil minimum tetap 0%",
        ],
    },
    {
        "object": "Performance Waktu Penyelesaian (%)",
        "formula": "100%+((100%-(Aktual Waktu Penyelesaian : 30)",
        "keterangan": [
            "Jika hasil waktu respon >100%, maka hasil maksimal tetap 100%",
            "Jika hasil waktu respon <0%, maka hasil minimum tetap 0%",
        ],
    },
    {
        "object": "Rata rata Waktu Respon dan rata rata Waktu Penyelesaian (%)",
        "formula": "Average (Performance Waktu Respon% dan Performance Waktu Penyelesaian %)",
        "keterangan": "-",
    },
)

# Muhammad Putra Tama Bayu Hargio, NRP JIMT24001 -- the Engineer Manage
# Service role holder among the IoT roster (2026-09-04). See its use in
# _iot_tasklist_sections for why "2. Detail Aktivitas..." filters to him
# specifically instead of the whole roster.
_ENGINEER_MANAGE_SERVICE_EMPLOYEE_ID: Final = "MTG-TF/2024020212"

_IOT_RESPON_PLACEHOLDER: Final = (
    '<div style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">'
    "<p>Data SLA belum tersedia untuk periode ini.</p>"
    "<p>vw_sla_iot_operations tidak dapat diakses (VPS unreachable) -- "
    "lihat docs/bast-e2e-plan.md §3.8 untuk rencana pemulihan.</p>"
    "</div>"
)


_LOGO_MAX_DIMENSION: Final = 300


def _resize_logo_bytes(image: bytes, max_dimension: int = _LOGO_MAX_DIMENSION) -> bytes:
    """logo_pama.png ships at 1786x2000 for a header slot capped at
    max-height:60px/max-width:150px (report_editor.html) -- html2canvas
    crashes the Chromium renderer trying to draw/read back an image that
    oversized (confirmed by isolating it: removing just this <img> lets the
    otherwise-identical timesheet page render fine). Downscaling keeps the
    exact same logo, format, and transparency (no RGB conversion, unlike
    _compress_evidence_image) -- only the pointless excess resolution goes.
    """
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(image)) as img:
            if img.width <= max_dimension and img.height <= max_dimension:
                return image
            img = img.copy()
            img.thumbnail((max_dimension, max_dimension))
            buffer = io.BytesIO()
            img.save(buffer, format=img.format or "PNG")
            return buffer.getvalue()
    except Exception:  # noqa: BLE001 - best-effort resize, never fatal
        return image


def _logo_data_uri(filename: str, mime: str) -> str:
    raw = (_TEMPLATE_DIR / "static" / "img" / filename).read_bytes()
    encoded = base64.b64encode(_resize_logo_bytes(raw))
    return f"data:{mime};base64,{encoded.decode()}"


LOGO_PAMA_URL: Final = _logo_data_uri("logo_pama.png", "image/png")
LOGO_CELERATES_URL: Final = _logo_data_uri("logo_celerates.jpg", "image/jpeg")


class _TaskRow:
    __slots__ = (
        "achievement",
        "category",
        "close_at",
        "employee_id",
        "end_date",
        "external_id",
        "requestor",
        "response_at",
        "source",
        "start_at",
        "status",
        "title",
        "updated_at",
        "version",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        source: str,
        external_id: str,
        employee_id: str | None,
        work_date: date,
        end_date: date | None,
        title: str | None,
        requestor: str | None,
        status: str | None,
        category: str | None,
        achievement: int | None,
        start_at: datetime | None,
        response_at: datetime | None,
        close_at: datetime | None,
        version: int,
        updated_at: datetime,
    ) -> None:
        self.source = source
        self.external_id = external_id
        self.employee_id = employee_id or ""
        self.work_date = work_date
        self.end_date = end_date
        self.title = title or ""
        self.requestor = requestor or ""
        self.status = status or ""
        self.category = category or ""
        self.achievement = achievement or 0
        self.start_at = start_at
        self.response_at = response_at
        self.close_at = close_at
        self.version = version
        self.updated_at = updated_at


class _TimesheetRow:
    __slots__ = (
        "activity",
        "employee_id",
        "external_id",
        "is_holiday",
        "project",
        "remarks",
        "source",
        "updated_at",
        "version",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        source: str,
        external_id: str,
        employee_id: str | None,
        work_date: date,
        activity: str | None,
        project: str | None,
        is_holiday: bool | None,
        remarks: str | None,
        version: int,
        updated_at: datetime,
    ) -> None:
        self.source = source
        self.external_id = external_id
        self.employee_id = employee_id or ""
        self.work_date = work_date
        self.activity = activity or ""
        self.project = project or ""
        self.is_holiday = bool(is_holiday)
        self.remarks = remarks or ""
        self.version = version
        self.updated_at = updated_at


class _AttendanceRow:
    __slots__ = (
        "check_in",
        "check_out",
        "employee_id",
        "external_id",
        "source",
        "updated_at",
        "version",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        source: str,
        external_id: str,
        employee_id: str | None,
        work_date: date,
        check_in: str | None,
        check_out: str | None,
        version: int,
        updated_at: datetime,
    ) -> None:
        self.source = source
        self.external_id = external_id
        self.employee_id = employee_id or ""
        self.work_date = work_date
        self.check_in = check_in or ""
        self.check_out = check_out or ""
        self.version = version
        self.updated_at = updated_at


_ABSENCE_LABELS: Final = {"cuti": "Cuti", "izin": "Izin", "sakit": "Sakit", "libur": "Libur"}


class _AbsenceRow:
    __slots__ = ("absence_type", "employee_id", "work_date")

    def __init__(self, employee_id: str, work_date: date, absence_type: str) -> None:
        self.employee_id = employee_id
        self.work_date = work_date
        self.absence_type = absence_type


class _EvidenceRow:
    __slots__ = (
        "caption",
        "content_type",
        "evidence_id",
        "image",
        "task_key",
        "task_source",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        evidence_id: str,
        task_source: str,
        task_key: str,
        work_date: date,
        caption: str,
        content_type: str,
        image: bytes,
    ) -> None:
        self.evidence_id = evidence_id
        self.task_source = task_source
        self.task_key = task_key
        self.work_date = work_date
        self.caption = caption
        self.content_type = content_type
        self.image = image


class _AttendanceEvidenceRow:
    __slots__ = ("caption", "content_type", "employee_id", "evidence_id", "image", "work_date")

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        evidence_id: str,
        employee_id: str,
        work_date: date,
        caption: str,
        content_type: str,
        image: bytes,
    ) -> None:
        self.evidence_id = evidence_id
        self.employee_id = employee_id
        self.work_date = work_date
        self.caption = caption
        self.content_type = content_type
        self.image = image


class _ScopeRow:
    __slots__ = ("external_id", "source", "updated_at", "version")

    def __init__(self, source: str, external_id: str, version: int, updated_at: datetime) -> None:
        self.source = source
        self.external_id = external_id
        self.version = version
        self.updated_at = updated_at


def compute_fingerprint(
    durable_rows: Iterable[tuple[str, str, int, datetime]],
    evidence_rows: Iterable[tuple[str, str]],
) -> str:
    """`durable_rows` = (source, external_id, version, updated_at); `evidence_rows` = (id, sha256).
    Pure function (§3.6) -- deterministic given the same rows regardless of read order.
    """
    durable_part = "".join(
        f"{source}:{external_id}:{version}:{updated_at.isoformat()}"
        for source, external_id, version, updated_at in sorted(
            durable_rows, key=lambda row: (row[0], row[1])
        )
    )
    evidence_part = "".join(
        f"{evidence_id}:{sha256}"
        for evidence_id, sha256 in sorted(evidence_rows, key=lambda row: row[0])
    )
    digest_input = f"durable:{durable_part}evidence:{evidence_part}"
    return hashlib.sha256(digest_input.encode()).hexdigest()


def _render(template_name: str, context: Mapping[str, object]) -> str:
    return _ENVIRONMENT.get_template(template_name).render(context)


def _scope_css(css: str, wrapper_class: str) -> str:
    """Rewrite every selector in a flat (no @media/@keyframes) CSS block so
    it only matches inside `.wrapper_class` -- "body" becomes the wrapper
    class itself (since the wrapper div plays body's role once embedded),
    everything else gets it as a descendant prefix. Comma-separated
    selectors are scoped individually.
    """
    scope = f".{wrapper_class}"

    def _scope_one(part: str) -> str:
        if part == "body":
            return scope
        if part.startswith("body "):
            return scope + part[len("body") :]
        return f"{scope} {part}"

    def _scope_selector_list(selectors: str) -> str:
        parts = (part.strip() for part in selectors.split(","))
        return ", ".join(_scope_one(part) for part in parts if part)

    def _scope_rule(match: re.Match[str]) -> str:
        return f"{_scope_selector_list(match[1])} {{{match[2]}}}"

    # Strip comments first -- a commented-out rule (evidence_aktivitas.html
    # has two) still contains a balanced { } pair, which would otherwise get
    # parsed as a real rule and desynchronize every match after it.
    uncommented = _CSS_COMMENT_PATTERN.sub("", css)
    return _CSS_RULE_PATTERN.sub(_scope_rule, uncommented)


def _body_only(html: str, wrapper_class: str) -> str:
    # report_editor.html renders all pages as one shared document (a single
    # <body> holding many .page divs), so a source template's own <style>
    # block can't just be reinjected verbatim -- even a bare "body { ... }"
    # rule would leak globally across every other page. Scope it to this
    # wrapper instead of dropping it outright (dropping it left, e.g.,
    # attendance_report_template.html's table with no border/blue header
    # and its logo at native PNG size instead of the intended small icon --
    # nearly everything in these templates is styled only via the stripped
    # <style>, not inline).
    match = _BODY_PATTERN.search(html)
    inner = match.group(1) if match is not None else html
    style_match = _STYLE_PATTERN.search(html)
    scoped_style = (
        f"<style>{_scope_css(style_match.group(1), wrapper_class)}</style>"
        if style_match is not None
        else ""
    )
    return f'<div class="{wrapper_class}">{scoped_style}{inner}</div>'


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    parts = value.strip().split(":")
    if len(parts) < 2:  # noqa: PLR2004
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _duration_hours(check_in: str, check_out: str) -> float | None:
    start = _parse_hhmm(check_in)
    end = _parse_hhmm(check_out)
    if start is None or end is None:
        return None
    start_minutes = start[0] * 60 + start[1]
    end_minutes = end[0] * 60 + end[1]
    if end_minutes < start_minutes:
        end_minutes += 24 * 60
    return (end_minutes - start_minutes) / 60


def _work_descriptions(tasks: Sequence[_TaskRow], employee_id: str) -> str:
    titles = sorted(
        {
            task.title.strip()
            for task in tasks
            if task.employee_id == employee_id and task.title.strip()
        }
    )
    return "; ".join(titles[:_MAX_WORK_DESCRIPTIONS])


def _timesheet_report(  # noqa: PLR0913, PLR0917
    employee: Employee,
    start: date,
    end: date,
    timesheets: Mapping[date, _TimesheetRow],
    attendance: Mapping[date, _AttendanceRow],
    absences: Mapping[date, str],
    work_descriptions: str,
    month_name: str,
    year: int,
) -> dict[str, object] | None:
    rows: list[dict[str, str]] = []
    totals = {"break": 0.0, "total": 0.0, "overtime": 0.0, "regular": 0.0}
    has_activity = False
    day = start
    while day <= end:
        record = timesheets.get(day)
        if record is None:
            # No timesheet row at all -- normally means nothing happened that
            # day, but it's also exactly what an approved cuti/izin/sakit day
            # looks like (the talent was never clocked in to begin with).
            # attendance_resolution_requests is the source of truth for that;
            # without it this rendered as a blank "working day" with no
            # indication anything was approved.
            absence_type = absences.get(day)
            if absence_type is not None:
                has_activity = True
            rows.append(
                {
                    "Date": day.strftime("%a, %b %-d, %Y"),
                    "Activity": "",
                    "Project Name": "",
                    "Work Description": "",
                    "Start Time": "",
                    "End Time": "",
                    "Break Hours": "",
                    "Total Hours": "",
                    "Over Time Hours": "",
                    "Regular Hours": "",
                    "Is Holiday": "H" if absence_type is not None else "",
                    "Remarks": (
                        _ABSENCE_LABELS.get(absence_type, absence_type)
                        if absence_type is not None
                        else ("Weekend" if day.weekday() >= 5 else "")  # noqa: PLR2004
                    ),
                }
            )
            day += timedelta(days=1)
            continue
        has_activity = True
        punches = attendance.get(day)
        # A PAMA schedule/timesheet sync can create a normal "Working Day" row
        # for a date PMO has since approved as Cuti/Izin/Sakit -- PAMA hasn't
        # caught up, or never will (same class of staleness as the schedule
        # sync disagreeing with an actual day off). record.remarks alone can't
        # catch that: it only reflects what PAMA sent. attendance_resolution_
        # requests (absences, keyed by day) is the PMO-approved source of
        # truth and overrides it here, same as the no-timesheet-row-at-all
        # case above.
        absence_type = absences.get(day)
        is_off_day = (
            record.is_holiday
            or record.remarks.strip().casefold() in _ABSENCE_LABELS
            or absence_type is not None
        )
        break_hours = total_hours = overtime_hours = regular_hours = 0.0
        start_time = end_time = ""
        if not is_off_day and punches is not None and punches.check_in and punches.check_out:
            start_time, end_time = punches.check_in, punches.check_out
            duration = _duration_hours(punches.check_in, punches.check_out)
            if duration is not None:
                break_hours = _STANDARD_BREAK_HOURS
                total_hours = max(duration - break_hours, 0.0)
                regular_hours = min(total_hours, _STANDARD_WORKDAY_HOURS)
                overtime_hours = max(total_hours - _STANDARD_WORKDAY_HOURS, 0.0)
        rows.append(
            {
                "Date": day.strftime("%a, %b %-d, %Y"),
                "Activity": "" if is_off_day else record.activity,
                "Project Name": "" if is_off_day else record.project,
                "Work Description": ("" if is_off_day or not start_time else work_descriptions),
                "Start Time": "" if is_off_day else start_time,
                "End Time": "" if is_off_day else end_time,
                "Break Hours": "" if is_off_day else f"{break_hours:.2f}",
                "Total Hours": "" if is_off_day else f"{total_hours:.2f}",
                "Over Time Hours": "" if is_off_day else f"{overtime_hours:.2f}",
                "Regular Hours": "" if is_off_day else f"{regular_hours:.2f}",
                "Is Holiday": "H" if is_off_day else "",
                "Remarks": (
                    _ABSENCE_LABELS.get(absence_type, absence_type)
                    if absence_type is not None
                    else record.remarks
                ),
            }
        )
        totals["break"] += break_hours
        totals["total"] += total_hours
        totals["overtime"] += overtime_hours
        totals["regular"] += regular_hours
        day += timedelta(days=1)
    if not has_activity:
        return None
    return {
        "nama": employee.name.upper(),
        "employee_id": str(employee.id),
        # v1-prod hardcodes the "Thu"/"Sat" weekday labels regardless of the
        # actual weekday (fastapi_server.py::_generate_single_employee_timesheet)
        # -- replicated verbatim for exact parity, not a bug introduced here.
        "start_date": f"Thu, {month_name} 01, {year}",
        "end_date": f"Sat, {month_name} {end.day:02d}, {year}",
        "total_break_hours": f"{totals['break']:.2f}",
        "total_hours": f"{totals['total']:.2f}",
        "total_overtime_hours": f"{totals['overtime']:.2f}",
        "total_regular_hours": f"{totals['regular']:.2f}",
        "timesheet_rows": rows,
    }


def _timesheet_sections(  # noqa: PLR0913, PLR0917
    roster: Sequence[Employee],
    tasks: Sequence[_TaskRow],
    timesheets: Sequence[_TimesheetRow],
    attendance: Sequence[_AttendanceRow],
    absences: Sequence[_AbsenceRow],
    start: date,
    end: date,
    month_name: str,
    year: int,
) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    for employee in roster:
        employee_id = str(employee.id)
        by_day = {row.work_date: row for row in timesheets if row.employee_id == employee_id}
        punches_by_day = {
            row.work_date: row for row in attendance if row.employee_id == employee_id
        }
        absences_by_day = {
            row.work_date: row.absence_type for row in absences if row.employee_id == employee_id
        }
        report = _timesheet_report(
            employee,
            start,
            end,
            by_day,
            punches_by_day,
            absences_by_day,
            _work_descriptions(tasks, employee_id),
            month_name,
            year,
        )
        if report is None:
            continue
        content = _render(
            "timesheet_report_template.html",
            {"reports": [report], "periode": f"{month_name} {year}", "logo_url": LOGO_PAMA_URL},
        )
        sections.append(
            {
                "type": "timesheet",
                "employee_name": employee.name.upper(),
                "content": content,
            }
        )
    return sections


def _developer_category_sections(  # noqa: PLR0913, PLR0917
    tasks: Sequence[_TaskRow],
    roster_names: Mapping[str, str],
    category: str,
    data_key: str,
    template_name: str,
    base_number: str,
    section_label: str,
    month_name: str,
) -> list[dict[str, object]]:
    closed = [
        task
        for task in tasks
        if task.category == category and task.status.strip().casefold() == _CLOSED
    ]
    items = [
        {
            "no": index,
            "task_list": task.title,
            "requestor": task.requestor,
            "pic": roster_names.get(task.employee_id, task.employee_id),
            "status": task.status,
            "start_date": task.work_date.strftime("%Y/%m/%d"),
            "end_date": task.end_date.strftime("%Y/%m/%d") if task.end_date else "N/A",
            # `closed` above is already filtered to Closed-status tasks only --
            # a task the report shows as Closed is done, full stop, regardless
            # of what the raw `achievement` field says (the source system
            # doesn't reliably keep that in sync once a ticket is closed).
            "pencapaian": "100",
        }
        for index, task in enumerate(closed, start=1)
    ]
    if not items:
        return []
    average = 100  # every item's pencapaian is forced to 100 above; keep the summary consistent
    # Wider Task List column (2026-09-04, report_editor.html/detail_aktivitas_*.html)
    # means most rows wrap to 1-2 lines instead of 3-4, so 10 rows/page leaves
    # real vertical slack on typical pages -- 14 packs that slack back in. Not
    # a guarantee for every possible mix of long task descriptions, so this
    # relies on autoFitPage's per-page shrink (report_editor.html) as the
    # fallback for a page that's still too tall, instead of silently cropping
    # like the pre-fix 10/page + no-shrink combination did.
    _DEVELOPER_TASKLIST_ITEMS_PER_PAGE = 14
    total_pages = (len(items) + _DEVELOPER_TASKLIST_ITEMS_PER_PAGE - 1) // _DEVELOPER_TASKLIST_ITEMS_PER_PAGE
    sections: list[dict[str, object]] = []
    for page_number in range(1, total_pages + 1):
        chunk = items[
            (page_number - 1) * _DEVELOPER_TASKLIST_ITEMS_PER_PAGE : page_number * _DEVELOPER_TASKLIST_ITEMS_PER_PAGE
        ]
        show_summary = page_number == total_pages
        title = f"{base_number}.{page_number} {section_label}"
        if total_pages > 1:
            title += f" (Halaman {page_number})"
        html = _render(
            template_name,
            {
                data_key: chunk,
                "summary_pencapaian": str(average) if show_summary else "",
                "month": month_name,
            },
        )
        sections.append(
            {
                "type": "tasklist",
                "title": title,
                "content": _body_only(html, "dev-tasklist-section"),
            }
        )
    return sections


def _developer_tasklist_sections(
    tasks: Sequence[_TaskRow], roster_names: Mapping[str, str], month_name: str
) -> list[dict[str, object]]:
    return [
        *_developer_category_sections(
            tasks,
            roster_names,
            _KUALITAS_KODE,
            "kualitas_kode_data",
            "tasklistdeveloper/detail_aktivitas_kualitas_kode.html",
            "2.1",
            _KUALITAS_KODE,
            month_name,
        ),
        *_developer_category_sections(
            tasks,
            roster_names,
            _WAKTU_RILIS,
            "waktu_rilis_data",
            "tasklistdeveloper/detail_aktivitas_waktu_rilis.html",
            "2.2",
            _WAKTU_RILIS,
            month_name,
        ),
        # Always empty in practice -- see module docstring point 2.
        *_developer_category_sections(
            tasks,
            roster_names,
            _DUKUNGAN_SUPPORT,
            "dukungan_support_data",
            "tasklistdeveloper/detail_aktivitas_dukungan_support.html",
            "2.3",
            _DUKUNGAN_SUPPORT,
            month_name,
        ),
    ]


_IOT_RESPON_SLA_MINUTES: Final = 15
_IOT_PENYELESAIAN_SLA_MINUTES: Final = 30
# docs/bast-e2e-plan.md §3.8 originally called for "50/page IoT respon",
# reproducing v1's own pagination. 2026-09-04: measured directly against the
# rendered DOM (18 columns x 50 rows) -- content came out ~2510px tall
# against the ~1121px A4 page box, more than double. Content past a .page's
# own box is invisible to html2canvas (it only captures the box, not the
# overflow), so this was silently dropping roughly the bottom half of every
# 50-row page from the exported PDF, and repeatedly rendering that much
# oversized content crashed Chromium ("Target crashed") on a dense report.
# 20 rows (~2510/50*20 =~ 1004px) comfortably clears one page.
_IOT_RESPON_ITEMS_PER_PAGE: Final = 20


def _iot_sla_performance(actual_minutes: float, sla_minutes: int) -> float:
    # achievement% = clamp(200 - 100*actual/SLA, 0, 100), from _IOT_PROBLEM_DATA's
    # own formula rows / bast-e2e-plan.md §3.8 recovery notes: 100% at meeting
    # the SLA exactly, degrading linearly to 0% at 2x the SLA.
    performance = 200 - (100 * actual_minutes / sla_minutes)
    return max(0.0, min(100.0, performance))


def _iot_tasklist_sections(
    tasks: Sequence[_TaskRow], roster_names: Mapping[str, str], month_name: str
) -> list[dict[str, object]]:
    problem_html = _render(
        "tasklistiotoperation/detail_problem_pihak_kedua.html",
        {"problem_data": _IOT_PROBLEM_DATA, "month": month_name},
    )
    closed_iot = [task for task in tasks if task.status.strip().casefold() == _CLOSED]
    sections: list[dict[str, object]] = [
        {
            "type": "tasklist",
            "title": "1. Detail Problem yang Ditangani oleh Pihak Kedua",
            "content": _body_only(problem_html, "iot-tasklist-section"),
        },
    ]

    # "2. Detail Aktivitas yang Ditangani oleh Pihak Kedua" is the Engineer
    # Manage Service role holder's own activity log (2026-09-04) -- Muhammad
    # Putra Tama Bayu Hargio, NRP JIMT24001, the one IoT-roster member whose
    # tasks come through tagged category="Detail Aktivitas Kualitas Kode"
    # instead of "IoT Operations" (a developer-style category, matching his
    # distinct role). Filtering by his own employee_id here rather than that
    # category string is the more direct, harder-to-accidentally-break match
    # for "this is specifically his section" -- category naming could drift
    # or get reused; his identity in the roster won't. "1. Detail Problem"
    # and "3. Detail Respon dan Resolution Time" above/below intentionally
    # stay unfiltered -- those cover the whole IoT roster, not just him.
    engineer_manage_service_tasks = [
        task for task in closed_iot if task.employee_id == _ENGINEER_MANAGE_SERVICE_EMPLOYEE_ID
    ]

    # "2. Detail Aktivitas" -- was rendered as one single .page regardless of
    # row count (some months have 800+ closed IoT tasks), overflowing the
    # same way every other unpaginated section did before today. Paginate it
    # the same way _developer_category_sections already does.
    aktivitas_data = [
        {
            "no": index,
            "detail_aktivitas": task.title,
            "tanggal_request": task.work_date.strftime("%d %B %Y"),
            "tanggal_penyelesaian": (task.end_date or task.work_date).strftime("%d %B %Y"),
            # 2026-09-04: was a hardcoded "8 Jam" literal (inherited verbatim
            # from v1-prod fastapi_server.py::_generate_iot_aktivitas_page,
            # which never computed it either) -- caught by inspection against
            # rows where request-to-completion visibly spans many days.
            # work_date/end_date only carry day precision here (unlike the
            # response/resolution section below, which has real start_at/
            # response_at/close_at timestamps), so this is days, not hours.
            "lead_time": (
                f"{((task.end_date or task.work_date) - task.work_date).days} Hari"
            ),
            "requestor_pic": (
                task.requestor if task.requestor not in ("", "User") else "Bagas Eko Prasetyo"
            ),
            "engineer_manage": roster_names.get(task.employee_id, task.employee_id),
        }
        for index, task in enumerate(engineer_manage_service_tasks, start=1)
        if task.title.strip() not in ("", "-", "N/A")
    ]
    aktivitas_pages = (
        len(aktivitas_data) + _ITEMS_PER_PAGE - 1
    ) // _ITEMS_PER_PAGE or 1
    for page_number in range(1, aktivitas_pages + 1):
        chunk = aktivitas_data[
            (page_number - 1) * _ITEMS_PER_PAGE : page_number * _ITEMS_PER_PAGE
        ]
        if not chunk:
            continue
        title = "2. Detail Aktivitas yang Ditangani oleh Pihak Kedua"
        if aktivitas_pages > 1:
            title += f" (Halaman {page_number})"
        sections.append(
            {
                "type": "tasklist",
                "title": title,
                "content": _body_only(
                    _render(
                        "tasklistiotoperation/detail_aktivitas_pihak_kedua.html",
                        {"aktivitas_data": chunk, "month": month_name},
                    ),
                    "iot-tasklist-section",
                ),
            }
        )

    # "3. Detail Respon dan Resolution Time" -- deferred to backlog on
    # 2026-08-19 (vw_sla_iot_operations was unreachable), now computed
    # directly from tasks.start_at/response_at/close_at per the formula this
    # module already documents in _IOT_PROBLEM_DATA and bast-e2e-plan.md §3.8.
    respon_source = [
        task
        for task in closed_iot
        if task.start_at is not None and task.response_at is not None and task.close_at is not None
    ]
    if not respon_source:
        sections.append(
            {
                "type": "tasklist",
                "title": "3. Detail Respon dan Resolution Time",
                "content": f'<div class="iot-tasklist-section">{_IOT_RESPON_PLACEHOLDER}</div>',
            }
        )
        return sections

    respon_data = []
    respon_performances: list[float] = []
    penyelesaian_performances: list[float] = []
    for index, task in enumerate(respon_source, start=1):
        respon_actual = (task.response_at - task.start_at).total_seconds() / 60
        penyelesaian_actual = (task.close_at - task.start_at).total_seconds() / 60
        performance_respon = _iot_sla_performance(respon_actual, _IOT_RESPON_SLA_MINUTES)
        performance_penyelesaian = _iot_sla_performance(
            penyelesaian_actual, _IOT_PENYELESAIAN_SLA_MINUTES
        )
        respon_performances.append(performance_respon)
        penyelesaian_performances.append(performance_penyelesaian)
        respon_data.append(
            {
                "no": index,
                "problem": task.title,
                "tanggal_problem": task.start_at.strftime("%d/%m/%Y"),
                "waktu_problem": task.start_at.strftime("%H:%M"),
                "tanggal_respon": task.response_at.strftime("%d/%m/%Y"),
                "tanggal_penyelesaian": task.close_at.strftime("%d/%m/%Y"),
                "waktu_penyelesaian": task.close_at.strftime("%H:%M"),
                "pic_pama": (
                    task.requestor if task.requestor not in ("", "User") else "Bagas Eko Prasetyo"
                ),
                "engineer": roster_names.get(task.employee_id, task.employee_id),
                "waktu_respon_menit": str(_IOT_RESPON_SLA_MINUTES),
                # The template's own header repeats "(Menit)"/"(%)" as two
                # identical sub-columns per metric (a v1-prod artifact, kept
                # verbatim) -- both slots get the same computed value rather
                # than an invented second number.
                "aktual_waktu_1": f"{respon_actual:.0f}",
                "aktual_waktu_2": f"{penyelesaian_actual:.0f}",
                "aktual_waktu_3": f"{respon_actual:.0f}",
                "aktual_waktu_4": f"{penyelesaian_actual:.0f}",
                "performance_respon_1": f"{performance_respon:.1f}",
                "performance_respon_2": f"{performance_respon:.1f}",
                "performance_penyelesaian_1": f"{performance_penyelesaian:.1f}",
                "performance_penyelesaian_2": f"{performance_penyelesaian:.1f}",
            }
        )

    mean_respon = sum(respon_performances) / len(respon_performances)
    mean_penyelesaian = sum(penyelesaian_performances) / len(penyelesaian_performances)
    summary_percentage = round((mean_respon + mean_penyelesaian) / 2, 1)

    respon_pages = (
        len(respon_data) + _IOT_RESPON_ITEMS_PER_PAGE - 1
    ) // _IOT_RESPON_ITEMS_PER_PAGE or 1
    for page_number in range(1, respon_pages + 1):
        chunk = respon_data[
            (page_number - 1) * _IOT_RESPON_ITEMS_PER_PAGE : page_number * _IOT_RESPON_ITEMS_PER_PAGE
        ]
        if not chunk:
            continue
        title = "3. Detail Respon dan Resolution Time"
        if respon_pages > 1:
            title += f" (Halaman {page_number})"
        show_summary = page_number == respon_pages
        sections.append(
            {
                "type": "tasklist",
                "title": title,
                "content": _body_only(
                    _render(
                        "tasklistiotoperation/detail_respon_resolution_time.html",
                        {
                            "respon_data": chunk,
                            "summary_percentage": summary_percentage if show_summary else "",
                        },
                    ),
                    "iot-tasklist-section",
                ),
            }
        )
    return sections


_EVIDENCE_MAX_DIMENSION: Final = 1280
_EVIDENCE_JPEG_QUALITY: Final = 65


def _compress_evidence_image(image: bytes) -> tuple[bytes, str]:
    """Downscale + recompress an evidence photo before embedding it as a data
    URI in the report HTML. Evidence rows come in up to 5MB each (byte_size
    check constraint on task_evidence) and a report can carry dozens of them
    -- embedded verbatim that inflates the assembled HTML to tens of MB,
    which crashes the headless-Chromium PDF renderer (pdf_export.py) with
    net::ERR_INSUFFICIENT_RESOURCES. Falls back to the original bytes if
    Pillow can't decode the image, so a bad row degrades rather than breaks
    the whole report.
    """
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(image)) as img:
            img = img.convert("RGB")
            img.thumbnail((_EVIDENCE_MAX_DIMENSION, _EVIDENCE_MAX_DIMENSION))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=_EVIDENCE_JPEG_QUALITY, optimize=True)
            return buffer.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 - best-effort compression, never fatal
        return image, "image/jpeg"


def _evidence_sections(
    evidence: Sequence[_EvidenceRow], tasks_by_key: Mapping[str, _TaskRow], month_name: str
) -> list[dict[str, object]]:
    closed_keys = {
        task.external_id
        for task in tasks_by_key.values()
        if task.status.strip().casefold() == _CLOSED
    }
    items = []
    for index, row in enumerate(
        (item for item in evidence if item.task_key in closed_keys), start=1
    ):
        compressed, content_type = _compress_evidence_image(row.image)
        items.append(
            {
                "number": index,
                "title": tasks_by_key[row.task_key].title if row.task_key in tasks_by_key else "",
                "image_path": f"data:{content_type};base64,{base64.b64encode(compressed).decode()}",
                "description": row.caption,
            }
        )
    if not items:
        return []
    # Two evidence-items per .page (report_editor.html gives every
    # html_sections entry exactly one .page div, see its {% elif
    # section.type == 'evidence' %} branch). This used to be one item per
    # page: an earlier version emitted every item into a single entry, so a
    # month with many evidence photos produced one .page whose content
    # overflowed far past the fixed A4 height -- html2canvas rasterises the
    # full scrollHeight of whatever it's pointed at (it doesn't respect CSS
    # page-break-inside), so that overflow crashed the renderer
    # (net::ERR_INSUFFICIENT_RESOURCES / Target crashed) instead of just
    # clipping. report_editor.html's autoFitPage() (2026-09-04) now measures
    # each page's real content height before capture and shrinks it to fit
    # -- the same mechanism that fixed task-list rows overflowing their page
    # -- so a bounded chunk (2 items, each already capped at max-height:400px
    # by evidence_aktivitas.html) fits safely instead of needing the
    # unbounded-content crash this chunking originally worked around.
    _EVIDENCE_ITEMS_PER_PAGE = 2
    chunks = [
        items[index : index + _EVIDENCE_ITEMS_PER_PAGE]
        for index in range(0, len(items), _EVIDENCE_ITEMS_PER_PAGE)
    ]
    return [
        {
            "type": "evidence",
            "title": "Evidence Aktivitas",
            "content": _body_only(
                _render(
                    "evidence/evidence_aktivitas.html",
                    {"evidence_data": chunk, "month": month_name},
                ),
                "evidence-section",
            ),
        }
        for chunk in chunks
    ]


# attendance_report_template.html's content (employee-info block + intro line +
# table header + footer declaration/signature, all at scale 1.0, post header-dedupe)
# measures ~778px before any table rows, plus ~24px per row -- fit against the
# .page's ~1123px height with a 5% margin so an outlier employee (some log up
# to ~26 rows/month) shrinks to fit one page instead of overflowing it, per the
# "1 page = 1 employee, never split" requirement (transform:scale, not pagination).
_ATTENDANCE_BASE_HEIGHT_PX: Final = 778
_ATTENDANCE_ROW_HEIGHT_PX: Final = 24
_ATTENDANCE_PAGE_HEIGHT_PX: Final = 1123
_ATTENDANCE_SCALE_MARGIN: Final = 0.95


def _attendance_scale(row_count: int) -> float:
    estimated_height = _ATTENDANCE_BASE_HEIGHT_PX + row_count * _ATTENDANCE_ROW_HEIGHT_PX
    if estimated_height <= _ATTENDANCE_PAGE_HEIGHT_PX:
        return 1.0
    return _ATTENDANCE_PAGE_HEIGHT_PX / estimated_height * _ATTENDANCE_SCALE_MARGIN


def _attendance_evidence_pages(
    employee_name: str, evidence_rows: Sequence[_AttendanceEvidenceRow]
) -> list[dict[str, object]]:
    # Reuses evidence_aktivitas.html (same one-item-per-page template as Task
    # Evidence, same reasoning: an oversized/uncompressed image overflowing
    # one .page crashes the Chromium renderer) -- existing/prior BAST output
    # had an "Attendance Evidence" page immediately after each employee's own
    # Attendance page, which this restores.
    pages: list[dict[str, object]] = []
    for index, row in enumerate(
        sorted(evidence_rows, key=lambda row: row.work_date), start=1
    ):
        compressed, content_type = _compress_evidence_image(row.image)
        item = {
            "number": index,
            "title": f"Attendance {row.work_date.strftime('%d/%m/%Y')} - {employee_name}",
            "image_path": f"data:{content_type};base64,{base64.b64encode(compressed).decode()}",
            "description": row.caption,
        }
        pages.append(
            {
                "type": "evidence",
                "title": f"Attendance Evidence - {employee_name}",
                "content": _body_only(
                    _render("evidence/evidence_aktivitas.html", {"evidence_data": [item]}),
                    "evidence-section",
                ),
            }
        )
    return pages


def _attendance_section(
    roster: Sequence[Employee],
    attendance: Sequence[_AttendanceRow],
    attendance_evidence: Sequence[_AttendanceEvidenceRow],
    start: date,
    end: date,
    dicetak: str,
) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for employee in roster:
        employee_id = str(employee.id)
        rows = sorted(
            (row for row in attendance if row.employee_id == employee_id),
            key=lambda row: row.work_date,
        )
        if not rows:
            continue
        attendance_rows: list[dict[str, object]] = []
        for row in rows:
            jam_kehadiran: list[tuple[str, str]] = []
            if row.check_out:
                jam_kehadiran.append((row.check_out, "out"))
            if row.check_in:
                jam_kehadiran.append((row.check_in, "in"))
            attendance_rows.append(
                {
                    "nrp": employee.external_id,
                    "nama": employee.name.upper(),
                    "tanggal_kehadiran": row.work_date.strftime("%d/%m/%Y"),
                    "jam_kehadiran": jam_kehadiran,
                }
            )
        reports.append(
            {
                "employee_id": employee_id,
                "nrp": employee.external_id,
                "nama": employee.name.upper(),
                "attendance_rows": attendance_rows,
            }
        )
    if not reports:
        return []
    # One employee's report per .page, mirroring the evidence-section fix
    # above and the timesheet section's existing per-employee pages -- a
    # roster-wide table (every employee's ~20+ workdays in one reports list)
    # rendered as a single html_sections entry overflows the same way the old
    # evidence section did (report_editor.html gives every entry exactly one
    # fixed-height .page), which crashed the headless-Chromium PDF renderer.
    #
    # Deliberately never split one employee across multiple pages (product
    # requirement: 1 page = 1 employee, always) -- an outlier employee (some
    # log up to ~26 attendance rows/month) instead gets scaled down via
    # _attendance_scale() to fit within one page, the same
    # transform:scale/transform-origin:top-left mechanism report_editor.html
    # already offers as a manual per-section slider (see --tasklist-scale/
    # --timesheet-scale), just computed automatically here instead of requiring
    # a human to drag it for every long-row employee.
    periode = f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
    sections: list[dict[str, object]] = []
    for report in reports:
        sections.append(
            {
                "type": "attendance",
                "title": "PAMA Attendance Report",
                "scale": _attendance_scale(len(report["attendance_rows"])),
                "content": _body_only(
                    _render(
                        "attendance_report_template.html",
                        {
                            "reports": [report],
                            "periode": periode,
                            "dicetak": dicetak,
                            "logo_url": LOGO_PAMA_URL,
                        },
                    ),
                    "attendance-section",
                ),
            }
        )
        # Attendance Evidence page(s) immediately follow that employee's own
        # Attendance page -- matches the prior/existing BAST layout.
        employee_evidence = [
            row for row in attendance_evidence if row.employee_id == report["employee_id"]
        ]
        if employee_evidence:
            sections.extend(_attendance_evidence_pages(report["nama"], employee_evidence))
    return sections


@dataclass(frozen=True, slots=True)
class AssembledReport:
    report_type: str
    year: int
    month: int
    fingerprint: str
    document: str
    editor_html: str


def _load_tasks(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_TaskRow, ...]:
    with connection.cursor(row_factory=class_row(_TaskRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT 'tasks' AS source, record_key AS external_id,
                   employee_id,
                   work_date,
                   end_date,
                   title,
                   requestor,
                   status,
                   category,
                   achievement,
                   start_at, response_at, close_at,
                   version, updated_at
            FROM tasks
            WHERE work_date BETWEEN %s AND %s
            ORDER BY work_date, record_key
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _load_timesheets(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_TimesheetRow, ...]:
    with connection.cursor(row_factory=class_row(_TimesheetRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT 'timesheets' AS source, record_key AS external_id,
                   employee_id,
                   work_date,
                   activity,
                   project,
                   is_holiday,
                   remarks,
                   version, updated_at
            FROM timesheets
            WHERE work_date BETWEEN %s AND %s
            ORDER BY work_date, record_key
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _load_attendance(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_AttendanceRow, ...]:
    # Approving a missing_clock_in/missing_clock_out/missing_both_worked
    # request in attendance_resolution.py only flips
    # attendance_resolution_requests.status to 'approved' -- it never writes
    # the PMO-corrected proposed_check_in/proposed_check_out back into the
    # attendance table itself, so BAST's timesheet (reading straight from
    # attendance) kept showing the original missing punch even after
    # approval. Scalar subqueries (not a JOIN) here so an attendance row
    # with multiple resolution requests over time (e.g. one rejected, one
    # later approved) can't multiply into duplicate attendance rows; only
    # the most recently reviewed approved request of the relevant type
    # wins, and each resolution type only ever supplies the side it
    # actually proposed (missing_clock_in never has a proposed_check_out).
    with connection.cursor(row_factory=class_row(_AttendanceRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT 'attendance' AS source, a.record_key AS external_id,
                   a.employee_id,
                   a.work_date,
                   COALESCE(
                       to_char(
                           (SELECT r.proposed_check_in FROM attendance_resolution_requests r
                            WHERE r.attendance_id = a.id AND r.status = 'approved'
                              AND r.resolution_type IN ('missing_clock_in', 'missing_both_worked')
                            ORDER BY r.reviewed_at DESC LIMIT 1),
                           'HH24:MI'
                       ),
                       to_char(a.check_in, 'HH24:MI'),
                       ''
                   ) AS check_in,
                   COALESCE(
                       to_char(
                           (SELECT r.proposed_check_out FROM attendance_resolution_requests r
                            WHERE r.attendance_id = a.id AND r.status = 'approved'
                              AND r.resolution_type IN ('missing_clock_out', 'missing_both_worked')
                            ORDER BY r.reviewed_at DESC LIMIT 1),
                           'HH24:MI'
                       ),
                       to_char(a.check_out, 'HH24:MI'),
                       ''
                   ) AS check_out,
                   a.version, a.updated_at
            FROM attendance a
            WHERE a.work_date BETWEEN %s AND %s
            ORDER BY a.work_date, a.record_key
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _load_absences(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_AbsenceRow, ...]:
    # Talent-mobile "Ajukan ke PMO" / PMO web Attendance Gaps ->
    # attendance_resolution_requests, approved absence requests only. A day
    # covered here usually has no attendance/timesheet row at all (that's why
    # it needed a resolution), but PAMA sync can also independently write a
    # normal "Working Day" timesheet row for the same date without knowing
    # about the approval -- _timesheet_report checks this mapping in BOTH
    # branches (row-present and row-absent) so the PMO-approved absence always
    # wins over a stale/contradicting PAMA row.
    with connection.cursor(row_factory=class_row(_AbsenceRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT employee_id, work_date, absence_type
            FROM attendance_resolution_requests
            WHERE resolution_type = 'absence'
              AND status = 'approved'
              AND work_date BETWEEN %s AND %s
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _load_evidence(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_EvidenceRow, ...]:
    with connection.cursor(row_factory=class_row(_EvidenceRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT DISTINCT ON (t.task_source, t.record_key)
                   e.id::text AS evidence_id, t.task_source, t.record_key AS task_key,
                   e.work_date, e.caption, e.content_type, e.image
            FROM task_evidence e
            JOIN tasks t ON t.id = e.task_id
            WHERE e.work_date BETWEEN %s AND %s
            ORDER BY t.task_source, t.record_key, e.uploaded_at DESC
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _load_attendance_evidence(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_AttendanceEvidenceRow, ...]:
    with connection.cursor(row_factory=class_row(_AttendanceEvidenceRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT DISTINCT ON (employee_id, work_date)
                   id::text AS evidence_id, employee_id, work_date, caption, content_type, image
            FROM attendance_evidence
            WHERE work_date BETWEEN %s AND %s
            ORDER BY employee_id, work_date, uploaded_at DESC
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


class _EvidenceScopeRow:
    __slots__ = ("evidence_id", "sha256")

    def __init__(self, evidence_id: str, sha256: str) -> None:
        self.evidence_id = evidence_id
        self.sha256 = sha256


def _load_evidence_scope(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[tuple[str, str], ...]:
    with connection.cursor(row_factory=class_row(_EvidenceScopeRow)) as cursor:
        _ = cursor.execute(
            "SELECT id::text AS evidence_id, sha256 FROM task_evidence"
            " WHERE work_date BETWEEN %s AND %s",
            (start, end),
        )
        return tuple((row.evidence_id, row.sha256) for row in cursor.fetchall())


def _load_holiday_scope(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_ScopeRow, ...]:
    with connection.cursor(row_factory=class_row(_ScopeRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT 'holidays' AS source, record_key AS external_id, version, updated_at
            FROM holidays
            WHERE work_date BETWEEN %s AND %s
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _assemble(
    report_type: str, year: int, month: int, dsn: str, employees: tuple[Employee, ...]
) -> AssembledReport:
    import calendar as calendar_module  # noqa: PLC0415

    role = _REPORT_ROLE[report_type]
    roster = tuple(employee for employee in employees if employee.role is role)
    roster_names = {str(employee.id): employee.name.upper() for employee in roster}
    start = date(year, month, 1)
    end = date(year, month, calendar_module.monthrange(year, month)[1])
    month_name = _MONTH_NAMES_ID[month]

    try:
        with psycopg.connect(dsn) as connection:
            _ = connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            tasks = _load_tasks(connection, start, end)
            timesheets = _load_timesheets(connection, start, end)
            attendance = _load_attendance(connection, start, end)
            absences = _load_absences(connection, start, end)
            evidence = _load_evidence(connection, start, end)
            attendance_evidence = _load_attendance_evidence(connection, start, end)
            evidence_scope = _load_evidence_scope(connection, start, end)
            holiday_scope = _load_holiday_scope(connection, start, end)
    except psycopg.Error as error:
        raise InfrastructureError(service="postgres", operation="assemble_bast") from error

    roster_ids = set(roster_names)
    tasks = tuple(task for task in tasks if task.employee_id in roster_ids)
    tasks_by_key = {task.external_id: task for task in tasks}

    # V1 (fastapi_server.py) always emits an unconditional "N. <Group>" header
    # section before each group -- this is also what report_editor.html's
    # {% set counters %} block keys off of to number "1.1 Timesheet <name>"
    # etc; without it counters.major never leaves 0 and every section prints
    # as "0.1", "0.2", ... regardless of group.
    html_sections: list[dict[str, object]] = [{"type": "timesheet_header", "title": "1. Timesheet"}]
    html_sections.extend(
        _timesheet_sections(
            roster, tasks, timesheets, attendance, absences, start, end, month_name, year
        )
    )
    html_sections.append({"type": "tasklist_header", "title": "2. Task List"})
    if role is EmployeeRole.DEVELOPER:
        html_sections.extend(_developer_tasklist_sections(tasks, roster_names, month_name))
    else:
        html_sections.extend(_iot_tasklist_sections(tasks, roster_names, month_name))
    html_sections.append({"type": "evidence_header", "title": "3. Evidence"})
    html_sections.extend(_evidence_sections(evidence, tasks_by_key, month_name))
    html_sections.append({"type": "attendance_header", "title": "4. Attendance"})
    html_sections.extend(
        _attendance_section(
            roster,
            attendance,
            attendance_evidence,
            start,
            end,
            datetime.now(JAKARTA).date().strftime("%d/%m/%Y"),
        )
    )

    context = {
        "html_sections": html_sections,
        "logo_pama_url": LOGO_PAMA_URL,
        "logo_celerates_url": LOGO_CELERATES_URL,
        "type": report_type,
        "month": month,
        "year": year,
    }
    document = _render("all_report_template.html", context)
    editor_html = _render("report_editor.html", context)

    scoped_rows = (*tasks, *timesheets, *attendance, *holiday_scope)
    durable_rows = [
        (row.source, row.external_id, row.version, row.updated_at) for row in scoped_rows
    ]
    fingerprint = compute_fingerprint(durable_rows, evidence_scope)

    return AssembledReport(
        report_type=report_type,
        year=year,
        month=month,
        fingerprint=fingerprint,
        document=document,
        editor_html=editor_html,
    )


async def assemble(report_type: str, year: int, month: int, dsn: str) -> AssembledReport:
    employees = await PostgresEmployeeSource(dsn).load()
    return await run_sync(_assemble, report_type, year, month, dsn, employees)


@final
class PostgresBastArtifactStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def save(self, report: AssembledReport) -> str:
        return await run_sync(self._save, report)

    def _save(self, report: AssembledReport) -> str:
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout_seconds
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    """
                    INSERT INTO bast_artifacts (report_type, year, month, fingerprint, document)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id::text
                    """,
                    (
                        report.report_type,
                        report.year,
                        report.month,
                        report.fingerprint,
                        report.document,
                    ),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="save_bast_artifact") from error
        return "" if row is None else str(row[0])
