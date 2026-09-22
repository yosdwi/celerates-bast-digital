"""Resolve a reply against the latest durable BAST closing reminder context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from digital_bast.application.talent_mobile_access import configured_talent_mobile_url
from digital_bast.application.workflow_control import WorkflowControlService
from digital_bast.bast_runtime import create_bast_snapshot_service
from digital_bast.bot.bast_reminder_context import BastReminderContextService
from digital_bast.bot.identity import ActivationService
from digital_bast.bot.payroll_attendance_natural import looks_like_natural_attendance_input
from digital_bast.config import get_settings
from digital_bast.domain.completion import DateRange
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import datetime

_DOMAIN_ALIASES: Final = {
    "attendance": "attendance",
    "absen": "attendance",
    "absensi": "attendance",
    "timesheet": "timesheet",
    "task": "task",
    "tasklist": "task",
    "task list": "task",
    "evidence": "evidence",
    "bukti": "evidence",
}


def _dsn() -> str | None:
    try:
        settings = get_settings()
    except (OSError, ValueError):
        return None
    return None if settings.database_dsn is None else settings.database_dsn.get_secret_value()


def _domain_hint(text: str) -> str | None:
    normalized = " ".join(text.strip().casefold().split())
    if normalized in _DOMAIN_ALIASES:
        return _DOMAIN_ALIASES[normalized]
    words = set(normalized.replace("&", " ").split())
    if {"attendance", "absen", "absensi"} & words:
        return "attendance"
    if "timesheet" in words:
        return "timesheet"
    if {"evidence", "bukti"} & words:
        return "evidence"
    if "task" in words or "tasklist" in words:
        return "task"
    return None


def _selected_domain(text: str, domains: tuple[str, ...]) -> tuple[str | None, bool]:
    stripped = text.strip()
    if stripped.isdigit():
        position = int(stripped)
        if 1 <= position <= len(domains):
            return domains[position - 1], True
        return None, True
    hinted = _domain_hint(text)
    if hinted is None and "attendance" in domains and looks_like_natural_attendance_input(text):
        hinted = "attendance"
    if hinted is None:
        return None, False
    return (hinted if hinted in domains else None), True


def _issues(title: str, issues: tuple[str, ...]) -> list[str]:
    lines = [f"*{title}*", ""]
    lines.extend(f"• {issue}" for issue in issues[:8])
    if len(issues) > 8:
        lines.append(f"• +{len(issues) - 8} lainnya")
    return lines


async def _public_url(dsn: str) -> str | None:
    try:
        return (await WorkflowControlService(dsn).talent_mobile_settings()).public_url
    except InfrastructureError:
        return None


async def reply_from_bast_context(
    text: str,
    jid: str,
    message_at: datetime,
) -> str | None:
    dsn = _dsn()
    if dsn is None:
        return None
    contexts = BastReminderContextService(dsn)
    context = await contexts.load(jid, now=message_at)
    if context is None:
        return None

    employee_id = await ActivationService(dsn).resolve(jid)
    if employee_id is None or employee_id != context.employee_id:
        await contexts.clear(jid)
        return "Reminder BAST ini sudah tidak cocok dengan identity WhatsApp aktif. Hubungi admin."

    domain, attempted = _selected_domain(text, context.domains)
    if domain is None:
        if not attempted:
            return None
        options = "\n".join(
            f"{index}. {item.title()}" for index, item in enumerate(context.domains, start=1)
        )
        return f"Pilihan itu tidak ada di reminder BAST ini. Pilih salah satu:\n\n{options}"

    period = DateRange(context.period_start, context.period_end)
    snapshot = await create_bast_snapshot_service().build(period)
    talent = next(
        (item for item in snapshot.talents if item.employee_id == employee_id),
        None,
    )
    if talent is None:
        await contexts.clear(jid)
        return "BAST periode ini sudah tidak punya item yang perlu kamu tindaklanjuti."
    blocker = next((item for item in talent.actionable if item.domain == domain), None)
    if blocker is None:
        return (
            f"Bagian {domain.title()} dari reminder ini sudah tidak perlu action dari kamu. "
            "Status terbaru sudah dimuat ulang."
        )

    if domain == "task":
        lines = _issues("Task List yang masih perlu perhatian", blocker.issues)
        lines.extend(
            (
                "",
                "Status Task List mengikuti Redmine/source.",
                "Update status dilakukan di source tersebut, bukan dari chatbot BAST.",
            )
        )
        return "\n".join(lines)

    if domain == "timesheet":
        lines = _issues("Timesheet yang masih perlu perhatian", blocker.issues)
        lines.extend(("", "Data Timesheet tetap mengikuti source operasional."))
        return "\n".join(lines)

    tab = "attendance" if domain == "attendance" else "tasks"
    url = configured_talent_mobile_url(
        employee_id,
        jid,
        period,
        tab,
        public_url=await _public_url(dsn),
    )
    title = (
        "Attendance yang perlu dilengkapi"
        if domain == "attendance"
        else "Evidence yang wajib dilengkapi"
    )
    lines = _issues(title, blocker.issues)
    if domain == "evidence":
        lines.extend(("", "Daftar ini hanya berisi task yang memang dikonfigurasi wajib evidence."))
    if url is None:
        command = "attendance" if domain == "attendance" else "tasklist"
        lines.extend(("", f"Ketik `{command}` untuk membuka flow existing dan memuat data terbaru."))
    else:
        lines.extend(("", "Buka item ini untuk menyelesaikannya:", url))
    return "\n".join(lines)
