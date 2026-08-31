"""Button-first Talent WhatsApp home, status, and request history views.

WhatsApp is the entry/notification surface; Talent Mobile is the primary work
surface. These projections therefore answer one question first: what does this
Talent actually need to do? Readiness/business state remains owned by existing
domain/application services.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING, Final

from digital_bast.bot.attendance_resolution import ResolutionStatus, ResolutionType
from digital_bast.bot.interactive import interactive
from digital_bast.domain.completion import MONTH_NAMES, DateRange, format_day
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import (
    completion_status,
    create_attendance_resolution_service,
    create_evidence_service,
)

if TYPE_CHECKING:
    from digital_bast.bot.attendance_resolution import AttendanceResolution
    from digital_bast.domain.completion import CompletionReport, EmployeeCompletion

_STATUS_WORDS: Final = frozenset({"status", "status saya", "lihat status", "cek status"})
_REQUEST_WORDS: Final = frozenset(
    {"request", "requests", "request saya", "pengajuan", "pengajuan saya"}
)
_REQUEST_HISTORY_LIMIT: Final = 10


def looks_like_status(text: str) -> bool:
    return text.strip().casefold() in _STATUS_WORDS


def looks_like_requests(text: str) -> bool:
    return text.strip().casefold() in _REQUEST_WORDS


def _period_now() -> DateRange:
    today = datetime.now(JAKARTA).date()
    return DateRange(today.replace(day=1), today)


def _period_label(period: DateRange) -> str:
    return f"{MONTH_NAMES[period.start.month - 1]} {period.start.year}"


def _mine(report: CompletionReport, employee_id: str) -> EmployeeCompletion | None:
    return next((item for item in report.employees if item.employee_id == employee_id), None)


def _time_label(value: time | None) -> str:
    return value.strftime("%H:%M") if value is not None else "-"


def _resolution_description(request: AttendanceResolution) -> str:
    if request.resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return f"Missing Clock In → {_time_label(request.proposed_check_in)}"
    if request.resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return f"Missing Clock Out → {_time_label(request.proposed_check_out)}"
    if request.resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return (
            f"Clock In {_time_label(request.proposed_check_in)} · "
            f"Clock Out {_time_label(request.proposed_check_out)}"
        )
    if request.absence_type is not None:
        return request.absence_type.value.capitalize()
    return "Attendance"


def _latest_request_by_day(
    items: tuple[AttendanceResolution, ...], period: DateRange
) -> dict[object, AttendanceResolution]:
    # AttendanceResolutionService.for_employee() is newest-first. Keep only
    # the latest decision for each day so an old rejection does not keep a day
    # actionable after a newer request has been submitted/approved.
    latest: dict[object, AttendanceResolution] = {}
    for item in items:
        if not period.start <= item.work_date <= period.end:
            continue
        latest.setdefault(item.work_date, item)
    return latest


async def _task_missing_count(employee_id: str, period: DateRange) -> int:
    candidates = tuple(
        item
        for item in await create_evidence_service().list_candidates(employee_id)
        if period.start <= item.work_date <= period.end
    )
    return sum(item.evidence_count <= 0 for item in candidates)


async def _home_counts(
    employee_id: str,
    period: DateRange,
    mine: EmployeeCompletion,
) -> tuple[int, int, int, int, int]:
    requests = await create_attendance_resolution_service().for_employee(employee_id)
    latest = _latest_request_by_day(requests, period)
    pending = sum(item.status is ResolutionStatus.PENDING for item in latest.values())
    rejected = sum(item.status is ResolutionStatus.REJECTED for item in latest.values())
    attendance_actions = len(mine.log_1_pama_evidence_days) + rejected
    task_actions = await _task_missing_count(employee_id, period)
    unavailable = len(mine.log_1_pama_missing_data_days)
    return attendance_actions + task_actions, pending, unavailable, attendance_actions, task_actions


async def home(
    employee_id: str,
    *,
    greeting: str | None = None,
    period: DateRange | None = None,
) -> str:
    active_period = period or _period_now()
    report = await completion_status(active_period)
    mine = _mine(report, employee_id)
    if mine is None:
        text = (
            f"*BAST Saya — {_period_label(active_period)}*\n\n"
            "Data BAST kamu belum tersedia untuk periode ini."
        )
    else:
        needs_action, pending, unavailable, _, _ = await _home_counts(
            employee_id, active_period, mine
        )
        lines = [
            f"Halo {mine.name} 👋",
            "",
            f"*BAST Saya — {_period_label(active_period)}*",
            "",
            f"Perlu tindakan     : {needs_action}",
            f"Menunggu PMO       : {pending}",
            f"Data belum tersedia: {unavailable}",
            "",
        ]
        if needs_action:
            lines.append("Selesaikan yang masih menjadi bagian kamu dari BAST Saya.")
        elif pending:
            lines.append("✅ Bagian kamu sudah selesai. Tinggal menunggu review PMO.")
        elif unavailable:
            lines.append(
                "✅ Tidak ada tindakan dari kamu. Data yang belum tersedia perlu ditindaklanjuti sistem/Admin."
            )
        else:
            lines.append("✅ Tidak ada tindakan yang perlu kamu lakukan.")
        text = "\n".join(lines)
    if greeting:
        text = f"{greeting}\n\n{text}"
    return interactive(
        text,
        ("bast-saya", "Buka BAST Saya"),
        ("attendance", "Attendance"),
        ("tasklist", "Task & Evidence"),
        footer='Kamu juga bisa ketik seperti "attendance Agustus"',
    )


async def status(employee_id: str, period: DateRange | None = None) -> str:
    active_period = period or _period_now()
    report = await completion_status(active_period)
    mine = _mine(report, employee_id)
    if mine is None:
        return interactive(
            f"*Status Saya — {_period_label(active_period)}*\n\nData belum tersedia.",
            ("bast-saya", "BAST Saya"),
            ("attendance", "Attendance"),
            ("tasklist", "Task & Evidence"),
        )

    needs_action, pending, unavailable, attendance_actions, task_actions = await _home_counts(
        employee_id, active_period, mine
    )
    lines = [
        f"*Status Saya — {_period_label(active_period)}*",
        "",
        f"Attendance       : {attendance_actions} perlu tindakan",
        f"Task & Evidence  : {task_actions} perlu dilengkapi",
        f"Menunggu PMO     : {pending}",
        f"Data unavailable : {unavailable}",
    ]
    if needs_action == 0 and pending == 0:
        lines.extend(("", "✅ Tidak ada pekerjaan BAST yang perlu kamu selesaikan sekarang."))
    elif needs_action == 0 and pending:
        lines.extend(("", "✅ Bagian kamu sudah selesai; tunggu keputusan PMO."))

    return interactive(
        "\n".join(lines),
        ("bast-saya", "BAST Saya"),
        ("attendance", "Attendance"),
        ("tasklist", "Task & Evidence"),
    )


async def requests(employee_id: str, period: DateRange | None = None) -> str:
    active_period = period or _period_now()
    items = tuple(
        request
        for request in await create_attendance_resolution_service().for_employee(employee_id)
        if active_period.start <= request.work_date <= active_period.end
    )
    if not items:
        return interactive(
            f"*Pengajuan — {_period_label(active_period)}*\n\nBelum ada pengajuan attendance pada periode ini.",
            ("bast-saya", "BAST Saya"),
            ("attendance", "Attendance"),
            ("tasklist", "Task & Evidence"),
        )

    icons = {
        ResolutionStatus.PENDING: "⏳",
        ResolutionStatus.APPROVED: "✅",
        ResolutionStatus.REJECTED: "❌",
    }
    labels = {
        ResolutionStatus.PENDING: "Menunggu PMO",
        ResolutionStatus.APPROVED: "Approved",
        ResolutionStatus.REJECTED: "Rejected",
    }
    lines = [f"*Pengajuan — {_period_label(active_period)}*", ""]
    for request in items[:_REQUEST_HISTORY_LIMIT]:
        lines.append(
            f"{icons[request.status]} {format_day(request.work_date)} — "
            f"{_resolution_description(request)}"
        )
        lines.append(f"   {labels[request.status]}")
        if request.status is ResolutionStatus.REJECTED and request.rejection_reason:
            lines.append(f"   Alasan: {request.rejection_reason}")
        lines.append("")
    if len(items) > _REQUEST_HISTORY_LIMIT:
        remaining = len(items) - _REQUEST_HISTORY_LIMIT
        lines.append(f"+ {remaining} pengajuan lain")

    return interactive(
        "\n".join(lines).strip(),
        ("bast-saya", "BAST Saya"),
        ("attendance", "Attendance"),
        ("tasklist", "Task & Evidence"),
    )
