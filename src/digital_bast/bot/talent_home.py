"""Button-first Talent WhatsApp home, status, and request history views.

These views are projections only. Completion/readiness and attendance request
state remain owned by the existing domain/application services; button IDs are
just deterministic entry points back into dm_workflow.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING, Final

from digital_bast.bot.attendance_resolution import ResolutionStatus, ResolutionType
from digital_bast.bot.interactive import interactive
from digital_bast.domain.completion import MONTH_NAMES, CheckState, DateRange, format_day
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import completion_status, create_attendance_resolution_service

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


def _state_icon(state: CheckState) -> str:
    if state is CheckState.COMPLETE:
        return "✅"
    if state is CheckState.NEEDS_REVIEW:
        return "⚠️"
    return "❌"


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


async def home(employee_id: str, *, greeting: str | None = None) -> str:
    """`greeting`, when given, is prepended above the usual "Halo {name} 👋" --
    used by cli._dm_onboarding right after a successful NRP bind to show a
    "connected" confirmation and this same home menu in one message, instead
    of the onboarding flow dead-ending into a differently-formatted summary
    that was never updated when this button-first home screen was added.
    """
    period = _period_now()
    report = await completion_status(period)
    mine = _mine(report, employee_id)
    if mine is None:
        text = "Halo. Data BAST kamu belum tersedia untuk periode ini."
        if greeting:
            text = f"{greeting}\n\n{text}"
        return interactive(
            text,
            ("status", "Status Saya"),
            ("attendance", "Attendance"),
            ("tasklist", "Task & Evidence"),
        )

    attendance_gaps = len(mine.log_1_pama.issues)
    evidence_gaps = len(mine.evidence.issues)
    if mine.state is CheckState.COMPLETE:
        text = (
            f"Halo {mine.name} 👋\n\n"
            f"*BAST {_period_label(period)}*\n"
            "✅ BAST kamu sudah lengkap."
        )
    else:
        text = (
            f"Halo {mine.name} 👋\n\n"
            f"*BAST {_period_label(period)}*\n"
            "⚠️ Masih ada yang perlu dilengkapi\n\n"
            f"Attendance : {attendance_gaps} perlu tindakan\n"
            f"Evidence   : {evidence_gaps} belum lengkap"
        )
        other_blockers = len(mine.timesheet.issues) + len(mine.task_list.issues)
        if other_blockers:
            text += f"\nLainnya    : {other_blockers} blocker — cek Status Saya"
    if greeting:
        text = f"{greeting}\n\n{text}"

    return interactive(
        text,
        ("status", "Status Saya"),
        ("attendance", "Attendance"),
        ("tasklist", "Task & Evidence"),
        footer="Kamu juga tetap bisa ketik dengan bahasa biasa",
    )


async def status(employee_id: str) -> str:
    period = _period_now()
    report = await completion_status(period)
    mine = _mine(report, employee_id)
    if mine is None:
        return interactive(
            "Status kamu belum tersedia untuk periode ini.",
            ("requests", "Request Saya"),
            ("attendance", "Attendance"),
            ("menu", "Menu"),
        )

    requests = await create_attendance_resolution_service().for_employee(employee_id)
    pending = sum(
        request.status is ResolutionStatus.PENDING
        and period.start <= request.work_date <= period.end
        for request in requests
    )
    lines = [
        f"*Status Saya — {_period_label(period)}*",
        "",
        f"{_state_icon(mine.log_1_pama.state)} Attendance : {len(mine.log_1_pama.issues)} gap",
        f"{_state_icon(mine.task_list.state)} Task List  : {len(mine.task_list.issues)} issue",
        f"{_state_icon(mine.evidence.state)} Evidence   : {len(mine.evidence.issues)} missing",
        f"{_state_icon(mine.timesheet.state)} Timesheet  : {len(mine.timesheet.issues)} issue",
        f"⏳ Request PMO: {pending} pending",
    ]
    if mine.state is CheckState.COMPLETE:
        lines.extend(("", "✅ Semua readiness check kamu lengkap."))

    return interactive(
        "\n".join(lines),
        ("requests", "Request Saya"),
        ("attendance", "Attendance"),
        ("tasklist", "Task & Evidence"),
    )


async def requests(employee_id: str) -> str:
    period = _period_now()
    items = tuple(
        request
        for request in await create_attendance_resolution_service().for_employee(employee_id)
        if period.start <= request.work_date <= period.end
    )
    if not items:
        return interactive(
            f"*Request Saya — {_period_label(period)}*\n\nBelum ada request attendance bulan ini.",
            ("status", "Status Saya"),
            ("attendance", "Attendance"),
            ("menu", "Menu"),
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
    lines = [f"*Request Saya — {_period_label(period)}*", ""]
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
        lines.append(f"+ {remaining} request lain di TalentOps Web")

    return interactive(
        "\n".join(lines).strip(),
        ("status", "Status Saya"),
        ("attendance", "Attendance"),
        ("menu", "Menu"),
    )
