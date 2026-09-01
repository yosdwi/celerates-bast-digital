from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal

import anyio
from pydantic import BaseModel, ValidationError, field_validator

from digital_bast.bot.whatsapp import strip_mentions
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.domain.completion import CheckResult, CheckState, DateRange, EmployeeCompletion
from digital_bast.domain.identity import canonical_text
from digital_bast.domain.models import EmployeeRole
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.cloudflare_workers_ai_chat import CloudflareWorkersAiChatClient
from digital_bast.operations import completion_status, load_roster

Dimension = Literal["readiness", "task", "evidence", "attendance", "timesheet"]
Scope = Literal["all", "developer", "iot"]
GroupInterpretation = GroupQuery | Literal["conversation", "unknown"] | None

_CLOSEOUT_GRACE_DAYS: Final = 7
_MAX_PERIOD_DAYS: Final = 366
_SCOPE_LABEL: Final[dict[Scope, str]] = {
    "all": "Semua Talent",
    "developer": "Developer",
    "iot": "IoT Operations",
}
_DIMENSION_LABEL: Final[dict[Dimension, str]] = {
    "readiness": "Status BAST",
    "task": "Task List",
    "evidence": "Evidence",
    "attendance": "Attendance",
    "timesheet": "Timesheet",
}
_SCOPE_ROLE: Final[dict[Scope, EmployeeRole | None]] = {
    "all": None,
    "developer": EmployeeRole.DEVELOPER,
    "iot": EmployeeRole.IOT_OPERATIONS,
}

_GROUP_SYSTEM_PROMPT: Final = (
    "Kamu adalah intent interpreter untuk grup kerja PMO Digital BAST. "
    "Kamu HANYA mengurai pertanyaan status/readiness, bukan menghitung status dan bukan "
    "mengambil keputusan bisnis. Pahami MAKSUD SELURUH KALIMAT; jangan memilih hanya karena "
    "satu keyword kebetulan muncul. Balas HANYA JSON valid dengan skema:\n"
    '{"kind":"status|conversation|unknown",'
    '"dimension":"readiness|task|evidence|attendance|timesheet|null",'
    '"scope":"all|developer|iot",'
    '"employee":"nama talent spesifik atau null",'
    '"start_date":"YYYY-MM-DD atau null","end_date":"YYYY-MM-DD atau null"}\n'
    "status dipakai untuk pertanyaan read-only seperti cek status, siapa yang kurang, siapa yang "
    "belum lengkap, kenapa belum ready, tasklist/evidence/attendance/timesheet bagaimana. "
    "dimension readiness jika menanyakan BAST/status keseluruhan; task untuk Task List/tasklist; "
    "evidence untuk Evidence Task; attendance untuk attendance/absensi/clock in/clock out; "
    "timesheet untuk timesheet. scope iot jika jelas menyebut IoT/IoT Operations, developer jika "
    "jelas menyebut Developer/dev, selain itu all. employee hanya jika benar-benar menyebut satu "
    "talent tertentu. conversation hanya untuk sapaan/terima kasih tanpa permintaan data. unknown "
    "jika maksudnya ambigu atau bukan query status.\n"
    'Contoh: "Conform aku mau cek status tasklist iot" -> '
    '{"kind":"status","dimension":"task","scope":"iot","employee":null,'
    '"start_date":null,"end_date":null}. '
    '"siapa developer yang evidence-nya masih kurang agustus 2026?" -> status/evidence/developer '
    "dengan seluruh Agustus 2026. "
    '"cek Farras tasklist agustus" -> status/task/all employee Farras dengan seluruh Agustus. '
    "Jika tidak ada periode, biarkan start_date/end_date null; aplikasi yang menentukan periode "
    "operasional default. Jangan mengarang tanggal."
)


@dataclass(frozen=True, slots=True)
class GroupQuery:
    dimension: Dimension
    scope: Scope
    period: DateRange
    employee: str | None = None


class _GroupDraft(BaseModel):
    kind: Literal["status", "conversation", "unknown"]
    dimension: Dimension | None = None
    scope: Scope = "all"
    employee: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("employee", "start_date", "end_date", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().casefold() in {"", "null", "none"}:
            return None
        return value


def _previous_month(today: date) -> DateRange:
    first_this_month = today.replace(day=1)
    last_previous = first_this_month - timedelta(days=1)
    return DateRange(last_previous.replace(day=1), last_previous)


def default_group_period(today: date) -> DateRange:
    """Return the PMO operational period when a read-only query omits it.

    During the first seven days of a month, PMO normally closes the previous
    BAST month. Afterwards the status context is month-to-date. Export and
    Generate BAST never use this default; their legacy explicit-period guard
    remains unchanged.
    """
    if today.day <= _CLOSEOUT_GRACE_DAYS:
        return _previous_month(today)
    return DateRange(today.replace(day=1), today)


def _client() -> CloudflareWorkersAiChatClient | None:
    try:
        settings = get_settings()
    except (ValidationError, SettingsConfigurationError, OSError):
        return None
    if settings.cloudflare_account_id is None or settings.cloudflare_api_token is None:
        return None
    return CloudflareWorkersAiChatClient(
        settings.cloudflare_account_id,
        settings.cloudflare_api_token.get_secret_value(),
        settings.cloudflare_workers_ai_model,
    )


def _draft_period(draft: _GroupDraft, today: date) -> DateRange | None:
    if draft.start_date is None and draft.end_date is None:
        return default_group_period(today)
    if draft.start_date is None or draft.end_date is None or draft.end_date < draft.start_date:
        return None
    if (draft.end_date - draft.start_date).days + 1 > _MAX_PERIOD_DAYS:
        return None
    return DateRange(draft.start_date, draft.end_date)


def _validated_query(draft: _GroupDraft, today: date) -> GroupInterpretation:
    if draft.kind != "status":
        return draft.kind
    if draft.dimension is None:
        return None
    period = _draft_period(draft, today)
    if period is None:
        return None
    employee = draft.employee.strip() if draft.employee else None
    return GroupQuery(draft.dimension, draft.scope, period, employee or None)


async def _interpret(text: str, today: date) -> GroupInterpretation:
    client = _client()
    if client is None:
        return None
    content = await client.complete(
        _GROUP_SYSTEM_PROMPT,
        f"Hari ini: {today.isoformat()}\nPesan grup: {strip_mentions(text)}",
    )
    if content is None:
        return None
    try:
        draft = _GroupDraft.model_validate_json(content)
    except ValidationError:
        return None
    return _validated_query(draft, today)


def _legacy_command(text: str) -> bool:
    """Return whether a high-confidence operational command must use the legacy path."""
    lowered = strip_mentions(text).strip().casefold()
    prefixes = (
        "export attendance",
        "export absensi",
        "generate bast",
        "buat bast",
        "bikin bast",
        "system status",
        "status sistem",
        "status server",
        "status docker",
        "restart ",
        "reboot ",
        "matikan ",
        "nyalakan ",
    )
    return any(lowered.startswith(prefix) for prefix in prefixes)


def _result(employee: EmployeeCompletion, dimension: Dimension) -> CheckResult | None:
    match dimension:
        case "task":
            return employee.task_list
        case "evidence":
            return employee.evidence
        case "attendance":
            return employee.log_1_pama
        case "timesheet":
            return employee.timesheet
        case "readiness":
            return None


def _state(employee: EmployeeCompletion, dimension: Dimension) -> CheckState:
    result = _result(employee, dimension)
    return employee.state if result is None else result.state


def _issue_count(employee: EmployeeCompletion, dimension: Dimension) -> int:
    result = _result(employee, dimension)
    if result is not None:
        return len(result.issues)
    checks = (
        employee.log_1_pama,
        employee.timesheet,
        employee.task_list,
        employee.evidence,
    )
    return sum(len(check.issues) for check in checks if check.state is not CheckState.COMPLETE)


def _readiness_domains(employee: EmployeeCompletion) -> str:
    missing = [
        label
        for label, result in (
            ("Attendance", employee.log_1_pama),
            ("Timesheet", employee.timesheet),
            ("Task List", employee.task_list),
            ("Evidence", employee.evidence),
        )
        if result.state is not CheckState.COMPLETE
    ]
    return ", ".join(missing) if missing else "Lengkap"


def _format_follow_up(employee: EmployeeCompletion, dimension: Dimension) -> str:
    if dimension == "readiness":
        return f"• {employee.name} — {_readiness_domains(employee)}"
    count = _issue_count(employee, dimension)
    if _state(employee, dimension) is CheckState.NEEDS_REVIEW:
        return f"• {employee.name} — perlu review"
    unit = "hari/item" if dimension in {"attendance", "timesheet"} else "item"
    return f"• {employee.name} — {count} {unit} belum lengkap"


async def _status_reply(query: GroupQuery) -> str:
    report = await completion_status(query.period, None)
    roster = await load_roster()
    role = _SCOPE_ROLE[query.scope]
    allowed_ids = {
        str(employee.id)
        for employee in roster
        if role is None or employee.role == role
    }
    employees = tuple(
        employee for employee in report.employees if employee.employee_id in allowed_ids
    )
    if query.employee:
        needle = canonical_text(query.employee)
        matches = tuple(
            employee for employee in employees if needle in canonical_text(employee.name)
        )
        if not matches:
            return (
                f'Talent "{query.employee}" tidak ditemukan pada scope {_SCOPE_LABEL[query.scope]} '
                f"untuk {query.period.label()}."
            )
        if len(matches) > 1:
            names = "\n".join(f"• {employee.name}" for employee in matches)
            return (
                "Ada beberapa talent yang cocok:\n"
                f"{names}\n\n"
                "Sebutkan nama yang lebih lengkap ya."
            )
        employees = matches

    title = _DIMENSION_LABEL[query.dimension]
    scope = _SCOPE_LABEL[query.scope]
    if not employees:
        return f"*{title} — {scope} — {query.period.label()}*\n\nTidak ada talent pada scope ini."

    complete = tuple(
        employee
        for employee in employees
        if _state(employee, query.dimension) is CheckState.COMPLETE
    )
    pending = tuple(
        employee
        for employee in employees
        if _state(employee, query.dimension) is not CheckState.COMPLETE
    )
    lines = [
        f"*{title} — {scope} — {query.period.label()}*",
        "",
        f"Lengkap        : {len(complete)}/{len(employees)}",
        f"Perlu follow-up: {len(pending)}",
    ]
    if pending:
        lines.extend(("", "Perlu follow-up:"))
        lines.extend(_format_follow_up(employee, query.dimension) for employee in pending)
    else:
        lines.extend(("", "✅ Semua talent pada scope ini sudah lengkap."))
    return "\n".join(lines)


async def reply(text: str) -> str:
    # Keep explicit export/generate/system commands on the existing audited
    # path. This wrapper only redesigns PMO read-only status queries.
    if _legacy_command(text):
        from digital_bast.cli import bot_reply  # noqa: PLC0415

        return bot_reply(text, channel="group")

    today = datetime.now(JAKARTA).date()
    interpreted = await _interpret(text, today)
    if isinstance(interpreted, GroupQuery):
        return await _status_reply(interpreted)

    # Conversation/unknown/LLM outage preserves the current group behavior
    # rather than inventing a deterministic substring guess.
    from digital_bast.cli import bot_reply  # noqa: PLC0415

    return bot_reply(text, channel="group")


def main() -> int:
    parser = argparse.ArgumentParser(prog="digital-bast-group")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reply_parser = subparsers.add_parser("reply")
    _ = reply_parser.add_argument("--text", required=True)
    args = parser.parse_args()
    if args.command == "reply":
        _ = sys.stdout.write(f"{anyio.run(reply, args.text)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
