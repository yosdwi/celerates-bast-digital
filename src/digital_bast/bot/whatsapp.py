from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from digital_bast.domain.completion import MONTH_NAMES, CheckState, DateRange

if TYPE_CHECKING:
    from digital_bast.domain.completion import CompletionReport
    from digital_bast.infrastructure.docker_status import SystemStatus

_MONTHS: Final = {
    **{name.casefold(): index for index, name in enumerate(MONTH_NAMES, start=1)},
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "mei": 5,
    "jun": 6,
    "jul": 7,
    "agu": 8,
    "ags": 8,
    "agt": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "des": 12,
}
_ISO_DATE: Final = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_PARTIAL_DATE: Final = re.compile(r"\b(\d{1,2})\b(?:\s+([A-Za-z]+))?(?:\s+(\d{4}))?")
_MENTION: Final = re.compile(r"@[\w.\-]+")
_MUTATION_WORDS: Final = (
    "restart",
    "reboot",
    "matikan",
    "hidupkan",
    "nyalakan",
    "shutdown",
    "kill",
    "stop container",
    "start container",
    "compose up",
    "compose down",
)
_SYSTEM_WORDS: Final = ("system status", "status sistem", "status docker", "status server")
_MINIMUM_RANGE_PARTS: Final = 2
_REPORT_TYPE_WORDS: Final = {
    "developer": "developer",
    "dev": "developer",
    "shifting": "shifting",
    "shift": "shifting",
    "iot": "shifting",
}
_STATE_ICONS: Final = {
    CheckState.COMPLETE: "✅",
    CheckState.INCOMPLETE: "❌",
    CheckState.NEEDS_REVIEW: "⚠️",
}
_SERVICE_LABELS: Final = {
    "postgres": "PostgreSQL",
    "redis": "Redis",
    "prefect-server": "Prefect Server",
    "prefect-services": "Prefect Services",
    "worker": "Worker",
    "runner": "Runner",
    "web-blue": "Web Blue",
    "web-green": "Web Green",
    "reverse-proxy": "Reverse Proxy",
}
MUTATION_REPLY: Final = (
    "V1 hanya mendukung pemeriksaan status. Perubahan container "
    "(restart/stop/start) tidak dijalankan lewat WhatsApp."
)
MISSING_PERIOD_REPLY: Final = (
    "Mohon sertakan rentang tanggal. Contoh: "
    "`status 1 sampai 31 Agustus` atau `status 2026-08-01 sampai 2026-08-31`."
)
MISSING_REPORT_TYPE_REPLY: Final = (
    "Mohon sertakan jenis laporan: `developer` atau `shifting`. Contoh: "
    "`export attendance developer 1 sampai 31 Agustus`."
)
HELP_REPLY: Final = (
    "*@conform — daftar perintah*\n\n"
    "• *Export absensi* (kirim file CSV)\n"
    "  `export attendance developer 1 sampai 20 agustus`\n"
    "  `export attendance shifting 1 sampai 20 agustus`\n\n"
    "• *Status kelengkapan BAST*\n"
    "  `status 1 sampai 31 agustus`\n\n"
    "• *Resume evidence*\n"
    "  `evidence 1 sampai 31 agustus`\n\n"
    "• *Buat dokumen BAST*\n"
    "  `generate bast 1 sampai 31 agustus`\n\n"
    "• *Status sistem*\n"
    "  `system status`\n\n"
    "Format tanggal bebas: `1 agustus`, `2026-08-01`, atau `1 sampai 20 agustus 2026`.\n"
    "Upload evidence lewat chat pribadi ke bot ini, bukan di grup."
)


class Intent(StrEnum):
    COMPLETION_STATUS = "completion-status"
    EVIDENCE_RESUME = "evidence-resume"
    EXPORT_ATTENDANCE = "export-attendance"
    GENERATE_BAST = "generate-bast"
    SYSTEM_STATUS = "system-status"
    UNSUPPORTED_MUTATION = "unsupported-mutation"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BotCommand:
    intent: Intent
    period: DateRange | None = None
    employee: str | None = None
    report_type: str | None = None


def _month_of(token: str | None) -> int | None:
    if token is None:
        return None
    return _MONTHS.get(token.casefold())


def _iso_dates(text: str) -> tuple[date, ...]:
    found: list[date] = []
    for match in _ISO_DATE.finditer(text):
        try:
            found.append(date(int(match[1]), int(match[2]), int(match[3])))
        except ValueError:
            continue
    return tuple(found)


def _partial_dates(text: str) -> tuple[tuple[int, int | None, int | None], ...]:
    return tuple(
        (int(match[1]), _month_of(match[2]), int(match[3]) if match[3] else None)
        for match in _PARTIAL_DATE.finditer(text)
    )


def _named_month(text: str) -> int | None:
    for token in re.findall(r"[A-Za-z]+", text):
        month = _month_of(token)
        if month is not None:
            return month
    return None


def _resolve(
    day: int,
    month: int | None,
    year: int | None,
    fallback_month: int,
    fallback_year: int,
) -> date | None:
    try:
        return date(year or fallback_year, month or fallback_month, day)
    except ValueError:
        return None


def parse_period(text: str, today: date) -> DateRange | None:
    iso = _iso_dates(text)
    if len(iso) >= _MINIMUM_RANGE_PARTS:
        return DateRange(iso[0], iso[1]) if iso[0] <= iso[1] else DateRange(iso[1], iso[0])
    partials = _partial_dates(_ISO_DATE.sub(" ", text))
    if len(partials) >= _MINIMUM_RANGE_PARTS:
        first, second = partials[0], partials[1]
        month = first[1] or second[1] or today.month
        year = first[2] or second[2] or today.year
        start = _resolve(first[0], first[1], first[2], month, year)
        end = _resolve(second[0], second[1], second[2], month, year)
        if start is not None and end is not None and start <= end:
            return DateRange(start, end)
        return None
    month = _named_month(text)
    if month is not None:
        year = partials[0][2] if partials and partials[0][2] else today.year
        last_day = calendar.monthrange(year, month)[1]
        return DateRange(date(year, month, 1), date(year, month, last_day))
    return None


_INTENT_RULES: Final[tuple[tuple[Intent, tuple[str, ...]], ...]] = (
    (Intent.UNSUPPORTED_MUTATION, _MUTATION_WORDS),
    (Intent.SYSTEM_STATUS, (*_SYSTEM_WORDS, "docker")),
    (Intent.EXPORT_ATTENDANCE, ("export", "absen")),
    (Intent.GENERATE_BAST, ("generate", "buat bast", "bikin bast")),
    (Intent.EVIDENCE_RESUME, ("evidence",)),
    (Intent.COMPLETION_STATUS, ("status", "cek")),
)


def _intent_of(text: str) -> Intent:
    for intent, words in _INTENT_RULES:
        if any(word in text for word in words):
            return intent
    return Intent.UNKNOWN


def _report_type_of(lowered: str) -> str | None:
    for word, report_type in _REPORT_TYPE_WORDS.items():
        if word in lowered:
            return report_type
    return None


def strip_mentions(text: str) -> str:
    return _MENTION.sub(" ", text).strip()


def parse_command(text: str, today: date) -> BotCommand:
    normalized = strip_mentions(text)
    lowered = normalized.casefold()
    intent = _intent_of(lowered)
    if intent in {Intent.UNKNOWN, Intent.SYSTEM_STATUS, Intent.UNSUPPORTED_MUTATION}:
        return BotCommand(intent)
    period = parse_period(normalized, today)
    if intent is not Intent.EXPORT_ATTENDANCE:
        return BotCommand(intent, period)
    return BotCommand(intent, period, report_type=_report_type_of(lowered))


def format_completion(report: CompletionReport) -> str:
    lines = [f"*Status BAST — {report.period.label()}*", ""]
    for index, employee in enumerate(report.employees, start=1):
        lines.append(f"{index}. {employee.name}")
        lines.append(
            f"Timesheet {_STATE_ICONS[employee.timesheet.state]} | "
            f"Task List {_STATE_ICONS[employee.task_list.state]} | "
            f"Evidence {_STATE_ICONS[employee.evidence.state]} | "
            f"Log 1 PAMA {_STATE_ICONS[employee.log_1_pama.state]}"
        )
        lines.append("")
    if not report.employees:
        lines.append("Tidak ada data karyawan pada periode ini.")
        return "\n".join(lines).strip()
    follow_up = [
        f"• {employee.name} — {issue}"
        for employee in report.employees
        for issue in employee.issues
    ]
    if follow_up:
        lines.append("*Perlu ditindaklanjuti*")
        lines.extend(follow_up)
    else:
        lines.append("Semua item BAST sudah lengkap.")
    return "\n".join(lines).strip()


def format_evidence_resume(report: CompletionReport) -> str:
    total = len(report.employees)
    lengkap = sum(1 for employee in report.employees if not employee.evidence.issues)
    lines = [f"*Evidence BAST — {report.period.label()}*", f"{lengkap}/{total} talent lengkap", ""]
    kurang = [
        f"• {employee.name} — {len(employee.evidence.issues)} Closed task tanpa evidence"
        for employee in report.employees
        if employee.evidence.issues
    ]
    if kurang:
        lines.append("Kurang:")
        lines.extend(kurang)
        lines.append("")
    not_closed = sum(
        len(employee.task_list.issues)
        for employee in report.employees
        if employee.task_list.state is CheckState.INCOMPLETE
    )
    total_tasks = sum(employee.total_tasks for employee in report.employees)
    lines.append(f"Task belum Closed: {not_closed} (dari {total_tasks})")
    lines.append("Lengkapi lewat chat pribadi ke bot ini.")
    return "\n".join(lines).strip()


def format_system_status(status: SystemStatus) -> str:
    lines = ["*Status Digital BAST*", ""]
    for service in status.services:
        icon = "✅" if service.ok else "❌"
        label = _SERVICE_LABELS.get(service.service, service.service)
        detail = service.health.capitalize() if service.health else service.state.capitalize()
        lines.append(f"{icon} {label} — {detail}")
    lines.append("")
    overall = "✅ Sehat" if status.overall == "healthy" else "❌ Bermasalah"
    lines.append(f"Overall: {overall}")
    return "\n".join(lines)
