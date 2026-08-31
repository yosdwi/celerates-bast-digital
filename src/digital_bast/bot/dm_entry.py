"""Top-level bound-Talent WhatsApp DM entrypoint.

WhatsApp is a button-first entry/notification surface; Talent Mobile is the
primary work surface for Attendance and Task & Evidence. Exact controlled
action IDs remain deterministic. Free-form Talent messages go through the
LLM-backed whole-sentence interpreter with a short-lived intent/period context;
we deliberately do not fall back to substring keyword routing when that
interpretation is ambiguous.

Existing PMO/onboarding/rebind flows and direct media evidence remain delegated
to dm_workflow unchanged.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime
from typing import Final

import anyio

from digital_bast.application.talent_mobile_access import configured_talent_mobile_url
from digital_bast.bot.attendance_resolution import ResolutionStatus
from digital_bast.bot.dm_workflow import reply as workflow_reply
from digital_bast.bot.interactive import interactive
from digital_bast.bot.talent_context import (
    TalentConversationContext,
    TalentIntent,
    TalentInterpretation,
)
from digital_bast.bot.talent_home import home as talent_home
from digital_bast.bot.talent_home import requests as talent_requests
from digital_bast.bot.talent_home import status as talent_status
from digital_bast.bot.whatsapp import GROUP_ONLY_COMMAND_IN_DM_REPLY
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.operations import (
    completion_status,
    create_activation_service,
    create_attendance_resolution_dm_state_service,
    create_attendance_resolution_service,
    create_evidence_service,
    create_llm_interpreter,
    create_talent_conversation_context_service,
    create_workflow_control_service,
)

_MENU_COMMANDS: Final = frozenset({"menu", "halo", "hai", "hi", "start", "help", "bantuan"})
_OVERVIEW_COMMANDS: Final = frozenset({"bast-saya", "bast saya", "buka bast saya"})
_TASK_MOBILE_COMMANDS: Final = frozenset(
    {"tasklist", "task list", "task & evidence", "task evidence", "evidence"}
)
_ATTENDANCE_MOBILE_COMMANDS: Final = frozenset({"attendance", "absen", "absensi"})
_STATUS_COMMANDS: Final = frozenset({"status", "status saya", "lihat status", "cek status"})
_REQUEST_COMMANDS: Final = frozenset(
    {"request", "requests", "request saya", "pengajuan", "pengajuan saya"}
)
# dm_workflow intentionally waits before automated replies. Preserve the same
# sending pattern for responses owned by this entrypoint.
_REPLY_DELAY_SECONDS: Final = (2.0, 5.0)


def _period_now() -> DateRange:
    today = datetime.now(JAKARTA).date()
    return DateRange(today.replace(day=1), today)


async def _saved_public_url() -> str | None:
    try:
        return (await create_workflow_control_service().talent_mobile_settings()).public_url
    except InfrastructureError:
        # Preserve TALENTOPS_PUBLIC_URL as the bootstrap fallback inside
        # configured_talent_mobile_url if the control-plane row is unavailable.
        return None


def _latest_request_statuses(
    requests: tuple[object, ...], period: DateRange
) -> tuple[int, int]:
    # Keep this helper structural so the DM entrypoint doesn't duplicate a
    # business model; AttendanceResolutionService already returns newest-first.
    latest: dict[object, object] = {}
    for raw in requests:
        work_date = getattr(raw, "work_date", None)
        if work_date is None or not period.start <= work_date <= period.end:
            continue
        latest.setdefault(work_date, raw)
    pending = sum(getattr(item, "status", None) is ResolutionStatus.PENDING for item in latest.values())
    rejected = sum(
        getattr(item, "status", None) is ResolutionStatus.REJECTED for item in latest.values()
    )
    return pending, rejected


async def _task_mobile_reply(
    employee_id: str,
    jid: str,
    period: DateRange,
    public_url: str | None,
) -> str:
    url = configured_talent_mobile_url(employee_id, jid, period, "tasks", public_url=public_url)
    candidates = tuple(
        item
        for item in await create_evidence_service().list_candidates(employee_id)
        if period.start <= item.work_date <= period.end
    )
    complete = sum(item.evidence_count > 0 for item in candidates)
    missing = len(candidates) - complete
    lines = [
        f"*Task & Evidence — {period.label()}*",
        "",
        f"Closed Task    : {len(candidates)}",
        f"Evidence lengkap: {complete}",
        f"Perlu dilengkapi: {missing}",
    ]
    if url is None:
        lines.extend(("", "Talent Mobile sedang tidak tersedia. Coba lagi atau hubungi admin."))
    else:
        lines.extend(("", "Upload Evidence langsung pada Task yang sesuai:", url))
    lines.extend(("", "Task/Evidence tidak membutuhkan approval PMO."))
    return "\n".join(lines)


async def _attendance_mobile_reply(
    employee_id: str,
    jid: str,
    period: DateRange,
    public_url: str | None,
) -> str:
    url = configured_talent_mobile_url(
        employee_id,
        jid,
        period,
        "attendance",
        public_url=public_url,
    )
    report = await completion_status(period)
    mine = next((item for item in report.employees if item.employee_id == employee_id), None)
    if mine is None:
        return f"Attendance kamu belum tersedia untuk {period.label()}."
    requests = await create_attendance_resolution_service().for_employee(employee_id)
    pending, rejected = _latest_request_statuses(requests, period)
    needs_action = len(mine.log_1_pama_evidence_days) + rejected
    unavailable = len(mine.log_1_pama_missing_data_days)
    lines = [
        f"*Attendance — {period.label()}*",
        "",
        f"Perlu tindakan     : {needs_action}",
        f"Menunggu PMO       : {pending}",
        f"Data belum tersedia: {unavailable}",
    ]
    if url is None:
        lines.extend(("", "Talent Mobile sedang tidak tersedia. Coba lagi atau hubungi admin."))
    else:
        lines.extend(("", "Buka Attendance untuk melihat tanggal dan menyelesaikan action:", url))
    lines.extend(
        (
            "",
            "Clock In/Out yang sudah ada tetap read-only; raw attendance client tidak diubah.",
        )
    )
    return "\n".join(lines)


def _clarification_reply() -> str:
    return interactive(
        "Aku belum yakin kamu mau cek bagian yang mana. Pilih salah satu ya.",
        ("bast-saya", "BAST Saya"),
        ("attendance", "Attendance"),
        ("tasklist", "Task & Evidence"),
        footer='Atau ketik natural, misalnya "attendance Agustus 2026"',
    )


def _exact_intent(normalized: str) -> TalentIntent | None:
    if normalized in _OVERVIEW_COMMANDS:
        return TalentIntent.HOME
    if normalized in _ATTENDANCE_MOBILE_COMMANDS:
        return TalentIntent.ATTENDANCE
    if normalized in _TASK_MOBILE_COMMANDS:
        return TalentIntent.TASKS
    if normalized in _STATUS_COMMANDS:
        return TalentIntent.STATUS
    if normalized in _REQUEST_COMMANDS:
        return TalentIntent.REQUESTS
    return None


async def _remember(
    jid: str,
    intent: TalentIntent,
    period: DateRange,
) -> None:
    await create_talent_conversation_context_service().save(
        jid,
        TalentConversationContext(intent, period),
    )


async def _dispatch_talent(
    employee_id: str,
    jid: str,
    interpretation: TalentInterpretation,
) -> str:
    if interpretation.period is None:
        return _clarification_reply()
    period = interpretation.period
    intent = interpretation.intent
    await _remember(jid, intent, period)
    if intent is TalentIntent.HOME:
        # Mobile Overview is intentionally not invented here: the current
        # Talent Mobile surface has Attendance/Tasks tabs only. This personal
        # status view is the stable `bast-saya` action until Overview ships.
        return await talent_status(employee_id, period)
    if intent is TalentIntent.ATTENDANCE:
        return await _attendance_mobile_reply(employee_id, jid, period, await _saved_public_url())
    if intent is TalentIntent.TASKS:
        return await _task_mobile_reply(employee_id, jid, period, await _saved_public_url())
    if intent is TalentIntent.STATUS:
        return await talent_status(employee_id, period)
    if intent is TalentIntent.REQUESTS:
        return await talent_requests(employee_id, period)
    return _clarification_reply()


async def _free_text_interpretation(
    text: str,
    jid: str,
) -> TalentInterpretation | None:
    interpreter = create_llm_interpreter()
    if interpreter is None:
        return None
    context = await create_talent_conversation_context_service().load(jid)
    return await interpreter.interpret_talent(text, datetime.now(JAKARTA).date(), context)


async def reply(text: str, jid: str) -> str:
    # A correction draft is a transactional workflow: once evidence has been
    # attached and the system is waiting for proposed clock/absence values,
    # navigation/NL interpretation must not steal the next message.
    if await create_attendance_resolution_dm_state_service().pending(jid) is not None:
        return await workflow_reply(text, jid)

    # Bare digits that survive wa-session are not menu-button shortcuts (those
    # are translated to action IDs by the transport). Preserve the legacy
    # numbered task/attendance evidence selection workflow.
    if text.strip().isdigit():
        return await workflow_reply(text, jid)

    employee_id = await create_activation_service().resolve(jid)
    if employee_id is None:
        # PMO, onboarding, rebind, and unknown senders remain entirely under
        # the existing workflow.
        return await workflow_reply(text, jid)

    normalized = text.strip().casefold()
    if normalized in _MENU_COMMANDS:
        period = _period_now()
        await _remember(jid, TalentIntent.HOME, period)
        await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
        return await talent_home(employee_id, period=period)

    exact = _exact_intent(normalized)
    if exact is not None:
        interpretation = TalentInterpretation(exact, _period_now())
        result = await _dispatch_talent(employee_id, jid, interpretation)
        await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
        return result

    interpretation = await _free_text_interpretation(text, jid)
    if interpretation is None or interpretation.intent is TalentIntent.UNKNOWN:
        await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
        return _clarification_reply()
    if interpretation.intent is TalentIntent.GROUP_ONLY:
        await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
        return GROUP_ONLY_COMMAND_IN_DM_REPLY
    if interpretation.intent is TalentIntent.CONVERSATION:
        # Let the existing persona/onboarding-safe conversation response own
        # wording; this path was explicitly classified as non-business first,
        # so no substring business routing is reintroduced here.
        return await workflow_reply(text, jid)

    result = await _dispatch_talent(employee_id, jid, interpretation)
    await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digital-bast-dm-entry")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reply_parser = subparsers.add_parser("reply")
    _ = reply_parser.add_argument("--text", required=True)
    _ = reply_parser.add_argument("--jid", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "reply":  # pragma: no cover - argparse invariant
        return 2
    result = anyio.run(reply, args.text, args.jid)
    _ = sys.stdout.write(f"{result}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
