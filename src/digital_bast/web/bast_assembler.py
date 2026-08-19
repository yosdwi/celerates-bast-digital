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
from digital_bast.infrastructure.local_completion_source import LocalEmployeeSource

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from digital_bast.domain.models import Employee

_TEMPLATE_DIR: Final = Path(__file__).resolve().parents[3] / "templates" / "bast"
_LOCAL_EMPLOYEE_FILE: Final = Path(__file__).resolve().parents[3] / "employee_data.json"
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

_IOT_RESPON_PLACEHOLDER: Final = (
    '<div style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">'
    "<p>Data SLA belum tersedia untuk periode ini.</p>"
    "<p>vw_sla_iot_operations tidak dapat diakses (VPS unreachable) -- "
    "lihat docs/bast-e2e-plan.md §3.8 untuk rencana pemulihan.</p>"
    "</div>"
)


def _logo_data_uri(filename: str, mime: str) -> str:
    encoded = base64.b64encode((_TEMPLATE_DIR / "static" / "img" / filename).read_bytes())
    return f"data:{mime};base64,{encoded.decode()}"


LOGO_PAMA_URL: Final = _logo_data_uri("logo_pama.png", "image/png")
LOGO_CELERATES_URL: Final = _logo_data_uri("logo_celerates.jpg", "image/jpeg")


class _TaskRow:
    __slots__ = (
        "achievement",
        "category",
        "employee_id",
        "end_date",
        "external_id",
        "requestor",
        "source",
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


def _body_only(html: str, wrapper_class: str) -> str:
    match = _BODY_PATTERN.search(html)
    inner = match.group(1) if match is not None else html
    return f'<div class="{wrapper_class}">{inner}</div>'


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
                    "Is Holiday": "",
                    "Remarks": "Weekend" if day.weekday() >= 5 else "",  # noqa: PLR2004
                }
            )
            day += timedelta(days=1)
            continue
        has_activity = True
        punches = attendance.get(day)
        break_hours = total_hours = overtime_hours = regular_hours = 0.0
        start_time = end_time = ""
        if not record.is_holiday and punches is not None and punches.check_in and punches.check_out:
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
                "Activity": record.activity,
                "Project Name": "" if record.is_holiday else record.project,
                "Work Description": (
                    "" if record.is_holiday or not start_time else work_descriptions
                ),
                "Start Time": "" if record.is_holiday else start_time,
                "End Time": "" if record.is_holiday else end_time,
                "Break Hours": "" if record.is_holiday else f"{break_hours:.2f}",
                "Total Hours": "" if record.is_holiday else f"{total_hours:.2f}",
                "Over Time Hours": "" if record.is_holiday else f"{overtime_hours:.2f}",
                "Regular Hours": "" if record.is_holiday else f"{regular_hours:.2f}",
                "Is Holiday": "H" if record.is_holiday else "",
                "Remarks": record.remarks,
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
        report = _timesheet_report(
            employee,
            start,
            end,
            by_day,
            punches_by_day,
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
            "pencapaian": str(task.achievement),
        }
        for index, task in enumerate(closed, start=1)
    ]
    if not items:
        return []
    average = sum(task.achievement for task in closed) // len(closed)
    total_pages = (len(items) + _ITEMS_PER_PAGE - 1) // _ITEMS_PER_PAGE
    sections: list[dict[str, object]] = []
    for page_number in range(1, total_pages + 1):
        chunk = items[(page_number - 1) * _ITEMS_PER_PAGE : page_number * _ITEMS_PER_PAGE]
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


def _iot_tasklist_sections(
    tasks: Sequence[_TaskRow], roster_names: Mapping[str, str], month_name: str
) -> list[dict[str, object]]:
    problem_html = _render(
        "tasklistiotoperation/detail_problem_pihak_kedua.html",
        {"problem_data": _IOT_PROBLEM_DATA, "month": month_name},
    )
    closed_iot = [task for task in tasks if task.status.strip().casefold() == _CLOSED]
    aktivitas_data = [
        {
            "no": index,
            "detail_aktivitas": task.title,
            "tanggal_request": task.work_date.strftime("%d %B %Y"),
            "tanggal_penyelesaian": (task.end_date or task.work_date).strftime("%d %B %Y"),
            # "Lead Time" is a hardcoded literal in v1-prod too (fastapi_server.py
            # ::_generate_iot_aktivitas_page), never computed -- kept as-is.
            "lead_time": "8 Jam",
            "requestor_pic": (
                task.requestor if task.requestor not in ("", "User") else "Bagas Eko Prasetyo"
            ),
            "engineer_manage": roster_names.get(task.employee_id, task.employee_id),
        }
        for index, task in enumerate(closed_iot, start=1)
        if task.title.strip() not in ("", "-", "N/A")
    ]
    aktivitas_html = _render(
        "tasklistiotoperation/detail_aktivitas_pihak_kedua.html",
        {"aktivitas_data": aktivitas_data, "month": month_name},
    )
    return [
        {
            "type": "tasklist",
            "title": "1. Detail Problem yang Ditangani oleh Pihak Kedua",
            "content": _body_only(problem_html, "iot-tasklist-section"),
        },
        {
            "type": "tasklist",
            "title": "2. Detail Aktivitas yang Ditangani oleh Pihak Kedua",
            "content": _body_only(aktivitas_html, "iot-tasklist-section"),
        },
        {
            "type": "tasklist",
            "title": "3. Detail Respon dan Resolution Time",
            "content": f'<div class="iot-tasklist-section">{_IOT_RESPON_PLACEHOLDER}</div>',
        },
    ]


def _evidence_sections(
    evidence: Sequence[_EvidenceRow], tasks_by_key: Mapping[str, _TaskRow], month_name: str
) -> list[dict[str, object]]:
    closed_keys = {
        task.external_id
        for task in tasks_by_key.values()
        if task.status.strip().casefold() == _CLOSED
    }
    items = [
        {
            "number": index,
            "title": tasks_by_key[row.task_key].title if row.task_key in tasks_by_key else "",
            "image_path": f"data:{row.content_type};base64,{base64.b64encode(row.image).decode()}",
            "description": row.caption,
        }
        for index, row in enumerate(
            (item for item in evidence if item.task_key in closed_keys), start=1
        )
    ]
    if not items:
        return []
    html = _render(
        "evidence/evidence_aktivitas.html", {"evidence_data": items, "month": month_name}
    )
    return [
        {
            "type": "evidence",
            "title": "Evidence Aktivitas",
            "content": _body_only(html, "evidence-section"),
        }
    ]


def _attendance_section(
    roster: Sequence[Employee],
    attendance: Sequence[_AttendanceRow],
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
                "nrp": employee.external_id,
                "nama": employee.name.upper(),
                "attendance_rows": attendance_rows,
            }
        )
    if not reports:
        return []
    html = _render(
        "attendance_report_template.html",
        {
            "reports": reports,
            "periode": f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}",
            "dicetak": dicetak,
            "logo_url": LOGO_PAMA_URL,
        },
    )
    return [
        {
            "type": "attendance",
            "title": "PAMA Attendance Report",
            "content": _body_only(html, "attendance-section"),
        }
    ]


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
            SELECT source, external_id,
                   payload->>'employee_id' AS employee_id,
                   work_date,
                   NULLIF(payload->>'end_date', '')::date AS end_date,
                   payload->>'title' AS title,
                   payload->>'requestor' AS requestor,
                   payload->>'status' AS status,
                   payload->>'category' AS category,
                   (payload->>'achievement')::int AS achievement,
                   version, updated_at
            FROM durable_records
            WHERE source = 'domain' AND entity_kind = 'task' AND work_date BETWEEN %s AND %s
            ORDER BY work_date, external_id
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
            SELECT source, external_id,
                   payload->>'employee_id' AS employee_id,
                   work_date,
                   payload->>'activity' AS activity,
                   payload->>'project' AS project,
                   (payload->>'is_holiday')::bool AS is_holiday,
                   payload->>'remarks' AS remarks,
                   version, updated_at
            FROM durable_records
            WHERE source = 'domain' AND entity_kind = 'timesheet' AND work_date BETWEEN %s AND %s
            ORDER BY work_date, external_id
            """,
            (start, end),
        )
        return tuple(cursor.fetchall())


def _load_attendance(
    connection: psycopg.Connection[object], start: date, end: date
) -> tuple[_AttendanceRow, ...]:
    # No source filter: real attendance lands with source='pama-direct'
    # (scripts/load_pama_attendance.py), not 'domain' -- see WP1 notes.
    with connection.cursor(row_factory=class_row(_AttendanceRow)) as cursor:
        _ = cursor.execute(
            """
            SELECT source, external_id,
                   payload->>'employee_id' AS employee_id,
                   work_date,
                   payload->>'check_in' AS check_in,
                   payload->>'check_out' AS check_out,
                   version, updated_at
            FROM durable_records
            WHERE entity_kind = 'attendance' AND work_date BETWEEN %s AND %s
            ORDER BY work_date, external_id
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
            SELECT id::text AS evidence_id, task_source, task_key, work_date,
                   caption, content_type, image
            FROM task_evidence
            WHERE work_date BETWEEN %s AND %s
            ORDER BY task_source, task_key, uploaded_at
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
            SELECT source, external_id, version, updated_at
            FROM durable_records
            WHERE entity_kind = 'holiday' AND work_date BETWEEN %s AND %s
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
            evidence = _load_evidence(connection, start, end)
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
        _timesheet_sections(roster, tasks, timesheets, attendance, start, end, month_name, year)
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
            roster, attendance, start, end, datetime.now(JAKARTA).date().strftime("%d/%m/%Y")
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
    employees = await LocalEmployeeSource(_LOCAL_EMPLOYEE_FILE).load()
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
