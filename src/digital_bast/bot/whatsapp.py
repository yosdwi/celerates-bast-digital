from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from html import escape
from typing import TYPE_CHECKING, Final

from digital_bast.domain.completion import MONTH_NAMES, CheckState, DateRange

if TYPE_CHECKING:
    from collections.abc import Callable

    from digital_bast.domain.completion import CompletionReport, EmployeeCompletion
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
_INDEX_WORDS: Final = {
    "satu": 1,
    "dua": 2,
    "tiga": 3,
    "empat": 4,
    "lima": 5,
    "enam": 6,
    "tujuh": 7,
    "delapan": 8,
    "sembilan": 9,
    "sepuluh": 10,
}
_INDEX_PATTERN: Final = re.compile(
    r"(?:poin|point|nomor|no\.?|number|#)\s*(\d{1,2}|" + "|".join(_INDEX_WORDS) + r")\b"
)
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
EVIDENCE_UPLOAD_IN_GROUP_REPLY: Final = (
    "Upload evidence-nya lewat chat pribadi ke aku ya, bukan di grup 🙏 "
    "Tinggal kirim foto/dokumennya langsung ke DM aku."
)
GROUP_ONLY_COMMAND_IN_DM_REPLY: Final = (
    "Perintah itu cuma jalan di grup kerja ya, coba ketik lagi di sana sambil mention @conform 🙏"
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
# Authoritative capability facts (§ persona) -- the single source of truth
# for both the LLM persona prompt (llm.py::persona_reply) and the
# deterministic fallback below. Never let the model invent a capability that
# isn't listed here; update this list, not the model's imagination, when a
# feature actually ships.
PERSONA_NAME: Final = "Conform AI"
PERSONA_CAPABILITIES: Final = (
    (
        "Di grup: cek status kesiapan BAST tim (ringkas + gambar matriks per talent), "
        "lihat talent mana yang Task List atau Evidence-nya masih kurang, export data "
        "attendance, generate dokumen laporan BAST, dan cek status sistem/server."
    ),
    (
        "Di chat pribadi (DM): kenalan sekali pakai NRP, lihat Task List & status "
        "Evidence pribadi, dibantu pilih Closed Task yang mana, terima upload foto/"
        "dokumen Evidence, dan lihat progress Evidence pribadi."
    ),
)
PERSONA_FALLBACK_REPLY: Final = (
    f"Halo 👋 Aku *{PERSONA_NAME}*, asisten otomatis buat Digital BAST.\n\n"
    "Tugasku bantu tim cek kesiapan BAST, monitor Task List & Evidence, "
    "export attendance, sampai generate laporan BAST. Kalau ada Evidence "
    "yang belum lengkap, aku juga bisa bantu tiap talent lewat chat "
    "pribadi biar grup tetap rapi.\n\n"
    "Kalau butuh bantuan, tinggal tanya aja di sini secara natural ya 😄"
)
_CONVERSATION_WORDS: Final = (
    "kenalin",
    "kenalan",
    "siapa kamu",
    "siapa nih",
    "siapa sih",
    "kamu siapa",
    "halo",
    "hai conform",
    "hallo",
    "hi conform",
    "assalamualaikum",
    "pagi conform",
    "siang conform",
    "sore conform",
    "malam conform",
    "makasih",
    "terima kasih",
    "thanks",
    "thank you",
    "mantap",
    "keren",
    "bisa ngapain",
    "bisa apa aja",
    "bantuin apa",
    "fungsi kamu",
    "tolong apa",
)
# "evidence" alone routes to EVIDENCE_RESUME (a period report -- see
# _INTENT_RULES below), which is the wrong flow for someone who actually
# wants to *send* a file: upload only works over DM (§ help text), so a
# group message asking to upload needs its own deterministic redirect,
# checked before intent/period resolution ever runs.
_EVIDENCE_UPLOAD_VERBS: Final = ("upload", "kirim", "submit", "send", "unggah")
_EVIDENCE_UPLOAD_NOUNS: Final = ("evidence", "bukti")


def wants_evidence_upload(text: str) -> bool:
    lowered = text.casefold()
    return any(verb in lowered for verb in _EVIDENCE_UPLOAD_VERBS) and any(
        noun in lowered for noun in _EVIDENCE_UPLOAD_NOUNS
    )


class Intent(StrEnum):
    COMPLETION_STATUS = "completion-status"
    EVIDENCE_RESUME = "evidence-resume"
    EXPORT_ATTENDANCE = "export-attendance"
    GENERATE_BAST = "generate-bast"
    SYSTEM_STATUS = "system-status"
    UNSUPPORTED_MUTATION = "unsupported-mutation"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


# Deterministic, group-only business intents that make no sense from a DM --
# COMPLETION_STATUS and EVIDENCE_RESUME are deliberately excluded: both are
# overloaded to also mean "my own" status/evidence in a DM (see
# cli.py::_SUMMARY_WORDS), so redirecting them to the group would be wrong.
GROUP_ONLY_DM_INTENTS: Final = frozenset(
    {Intent.EXPORT_ATTENDANCE, Intent.GENERATE_BAST, Intent.SYSTEM_STATUS}
)


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
    (Intent.COMPLETION_STATUS, ("status", "cek", "detail", "kenapa")),
    # Checked last -- a business keyword above always wins first, so smalltalk
    # phrased with an actual business word ("makasih ya sudah export") still
    # routes to the business intent, never to conversation.
    (Intent.CONVERSATION, _CONVERSATION_WORDS),
)
# Best-effort only, deliberately narrow: "detail <name> ..." is unambiguous
# enough for a regex (the name is always the very next word). "kenapa <name>
# belum lengkap ..." and a bare "<name> kurang apa?" have too much free-form
# text around the name for a regex to isolate reliably -- those need the LLM
# interpreter (llm.py's BotCommandDraft.employee), which is the primary path
# anyway; this fallback only degrades to a full group summary for those.
_EMPLOYEE_DETAIL_PATTERN: Final = re.compile(r"\bdetail\s+([A-Za-z][\w.\-]*)", re.IGNORECASE)

# "export attendance developer atas nama Muhammad Taufiq dari tanggal 21
# agustus - 27 agustus 2026" -- capture everything after "atas nama" up to
# whatever date/period phrasing follows, not just one word, since a person's
# full name is routinely multiple words and the date range sits in the same
# message with no other delimiter.
_EXPORT_EMPLOYEE_PATTERN: Final = re.compile(
    r"atas\s+nama\s+([A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*)*?)"
    r"(?=\s+(?:dari|tanggal|periode|untuk|,)\b|\s*$)",
    re.IGNORECASE,
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


def extract_index(text: str) -> int | None:
    """Pull an explicit 1-based reference ("poin 1", "nomor satu", bare "2")
    out of free text. Never guesses -- returns None rather than a wrong index.
    """
    match = _INDEX_PATTERN.search(text.casefold())
    if match is not None:
        token = match[1]
        return int(token) if token.isdigit() else _INDEX_WORDS.get(token)
    stripped = text.strip().casefold()
    if stripped.isdigit():
        return int(stripped)
    return _INDEX_WORDS.get(stripped)


def _employee_of(text: str) -> str | None:
    match = _EMPLOYEE_DETAIL_PATTERN.search(text)
    if match is None:
        return None
    word = match[1]
    return None if _month_of(word) is not None else word


def _export_employee_of(text: str) -> str | None:
    match = _EXPORT_EMPLOYEE_PATTERN.search(text)
    if match is None:
        return None
    name = match[1].strip()
    return name or None


def parse_command(text: str, today: date) -> BotCommand:
    normalized = strip_mentions(text)
    lowered = normalized.casefold()
    intent = _intent_of(lowered)
    if intent in {
        Intent.UNKNOWN,
        Intent.SYSTEM_STATUS,
        Intent.UNSUPPORTED_MUTATION,
        Intent.CONVERSATION,
    }:
        return BotCommand(intent)
    period = parse_period(normalized, today)
    if intent is Intent.EXPORT_ATTENDANCE:
        return BotCommand(
            intent,
            period,
            report_type=_report_type_of(lowered),
            employee=_export_employee_of(normalized),
        )
    employee = _employee_of(normalized) if intent is Intent.COMPLETION_STATUS else None
    return BotCommand(intent, period, employee=employee)


def _ratio(report: CompletionReport, pick: Callable[[EmployeeCompletion], CheckState]) -> str:
    ok = sum(1 for employee in report.employees if pick(employee) is CheckState.COMPLETE)
    return f"{ok}/{len(report.employees)}"


def format_completion(report: CompletionReport) -> str:
    """Compact group-chat summary (§7) -- counts and ratios only, never a
    per-employee-per-date dump. Use format_employee_detail for one talent.
    """
    if not report.employees:
        return (
            f"*Status BAST — {report.period.label()}*\n\nTidak ada data karyawan pada periode ini."
        )
    complete = sum(1 for employee in report.employees if employee.state is CheckState.COMPLETE)
    total = len(report.employees)
    lines = [
        f"*Status BAST — {report.period.label()}*",
        "",
        f"Overall        : {'✅ Siap' if report.state is CheckState.COMPLETE else '⚠️ Belum siap'}",
        f"Talent lengkap : {complete}/{total}",
        "",
        f"Log 1 PAMA : {_ratio(report, lambda e: e.log_1_pama.state)}",
        f"Timesheet  : {_ratio(report, lambda e: e.timesheet.state)}",
        f"Task List  : {_ratio(report, lambda e: e.task_list.state)}",
        f"Evidence   : {_ratio(report, lambda e: e.evidence.state)}",
        "",
    ]
    remaining = total - complete
    lines.append(
        f"{remaining} talent masih perlu follow-up."
        if remaining
        else "Semua item BAST sudah lengkap."
    )
    if remaining:
        lines.append("Detail per talent: kirim `detail <nama>`.")
    return "\n".join(lines).strip()


_ISSUE_LINE: Final = re.compile(r"^(\d{1,2}) [A-Za-z]+ — (.+)$")


def _compress_days(days: list[int]) -> str:
    ordered = sorted(set(days))
    spans: list[str] = []
    start = prev = ordered[0]
    for day in ordered[1:]:
        if day == prev + 1:
            prev = day
            continue
        spans.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = day
    spans.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(spans)


def _aggregate_issues(issues: tuple[str, ...]) -> list[str]:
    """Group repeated per-date issue lines (domain/completion.py emits one
    line per date) by their reason text, compressing the dates into ranges --
    e.g. 19 "<day> Agustus — Clock In ... belum terisi ..." lines collapse to
    one "19 hari — Clock In ... ; 3-14, 18-21, ..." line. Task-scoped issues
    (no date prefix, e.g. task_list/evidence) pass through unchanged since
    they are already one line per task, not per date.
    """
    by_reason: dict[str, list[int]] = {}
    order: list[str] = []
    passthrough: list[str] = []
    for issue in issues:
        match = _ISSUE_LINE.match(issue)
        if match is None:
            passthrough.append(issue)
            continue
        day, reason = int(match[1]), match[2]
        if reason not in by_reason:
            by_reason[reason] = []
            order.append(reason)
        by_reason[reason].append(day)
    grouped = [
        f"{len(by_reason[reason])} hari — {reason} ({_compress_days(by_reason[reason])})"
        for reason in order
    ]
    return [*grouped, *passthrough]


def format_employee_detail(employee: EmployeeCompletion, period: DateRange) -> str:
    """On-demand single-talent detail (§8): same underlying issues as
    format_completion's group summary would have dumped, but grouped by
    reason with compressed date ranges instead of one line per date.
    """
    lines = [f"*{employee.name} — BAST {period.label()}*", ""]
    for label, result in (
        ("Log 1 PAMA", employee.log_1_pama),
        ("Timesheet", employee.timesheet),
        ("Task List", employee.task_list),
        ("Evidence", employee.evidence),
    ):
        lines.append(f"{_STATE_ICONS[result.state]} {label}")
        if result.issues:
            lines.extend(_aggregate_issues(result.issues))
        else:
            lines.append("Lengkap.")
        lines.append("")
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


# Plain-text glyphs (not color-emoji codepoints like the WhatsApp-facing
# ✅/❌/⚠️ in _STATE_ICONS) -- headless Chromium on a bare VPS has no
# color-emoji font installed and renders those as empty boxes. A CSS badge
# needs no font support beyond Arial's ASCII/Latin-1 glyphs.
_MATRIX_BADGE: Final = {
    CheckState.COMPLETE: ("#2e7d32", "OK"),
    CheckState.INCOMPLETE: ("#c62828", "X"),
    CheckState.NEEDS_REVIEW: ("#ef6c00", "!"),
}


def _badge(state: CheckState) -> str:
    color, glyph = _MATRIX_BADGE[state]
    return (
        f'<span style="display:inline-block;min-width:20px;padding:2px 6px;'
        f"border-radius:10px;background:{color};color:#fff;font-weight:bold;"
        f'font-size:11px;">{glyph}</span>'
    )


def render_status_matrix_html(report: CompletionReport) -> str:
    """Self-contained HTML (no external assets) for
    infrastructure/pdf_export.py::render_png -- the compact PNG matrix
    attached alongside format_completion's text summary (§7). One row per
    talent; a #card element frames the screenshot.
    """
    rows = "\n".join(
        f"<tr><td class='name'>{escape(employee.name)}</td>"
        f"<td>{_badge(employee.log_1_pama.state)}</td>"
        f"<td>{_badge(employee.timesheet.state)}</td>"
        f"<td>{_badge(employee.task_list.state)}</td>"
        f"<td>{_badge(employee.evidence.state)}</td></tr>"
        for employee in report.employees
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin:0; }}
#card {{ display:inline-block; font-family:Arial,sans-serif; background:#fff; padding:16px; }}
h1 {{ font-size:16px; margin:0 0 10px; }}
table {{ border-collapse:collapse; font-size:13px; }}
th, td {{ border:1px solid #ccc; padding:6px 12px; text-align:center; }}
th {{ background:#f0f0f0; }}
td.name {{ text-align:left; font-weight:bold; }}
</style></head><body>
<div id="card">
<h1>Status BAST — {escape(report.period.label())}</h1>
<table>
<tr><th>Talent</th><th>Log PAMA</th><th>Timesheet</th><th>Task List</th><th>Evidence</th></tr>
{rows}
</table>
</div>
</body></html>"""
