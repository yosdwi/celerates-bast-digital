"""Thin DM entry wrapper that keeps existing workflow logic intact.

Only the two high-friction Talent menu entries (Attendance and Task & Evidence)
are redirected to the signed mobile card surface when its public URL is
configured. Every other message delegates to ``dm_workflow.reply`` unchanged,
and evidence media still goes through ``dm_workflow.evidence``.
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
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import (
    completion_status,
    create_activation_service,
    create_attendance_resolution_service,
    create_evidence_service,
)

_TASK_MOBILE_COMMANDS: Final = frozenset(
    {"tasklist", "task list", "task & evidence", "task evidence", "evidence"}
)
_ATTENDANCE_MOBILE_COMMANDS: Final = frozenset({"attendance", "absen", "absensi"})
# dm_workflow intentionally waits before automated replies. Preserve the same
# timing on the two commands intercepted here so this UX change does not alter
# the account's WhatsApp sending pattern.
_REPLY_DELAY_SECONDS: Final = (2.0, 5.0)


def _period() -> DateRange:
    today = datetime.now(JAKARTA).date()
    return DateRange(today.replace(day=1), today)


async def _task_mobile_reply(employee_id: str, jid: str, period: DateRange) -> str | None:
    url = configured_talent_mobile_url(employee_id, jid, period, "tasks")
    if url is None:
        return None
    candidates = tuple(
        item
        for item in await create_evidence_service().list_candidates(employee_id)
        if period.start <= item.work_date <= period.end
    )
    complete = sum(item.evidence_count > 0 for item in candidates)
    missing = len(candidates) - complete
    await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
    return (
        f"*Task & Evidence — {period.label()}*\n\n"
        f"Closed task   : {len(candidates)}\n"
        f"Evidence      : {complete}/{len(candidates)}\n"
        f"Belum lengkap : {missing}\n\n"
        "Upload langsung dari card task yang sesuai:\n"
        f"{url}\n\n"
        "Tidak perlu pilih task dan upload satu-per-satu lewat chat."
    )


async def _attendance_mobile_reply(employee_id: str, jid: str, period: DateRange) -> str | None:
    url = configured_talent_mobile_url(employee_id, jid, period, "attendance")
    if url is None:
        return None
    report = await completion_status(period)
    mine = next((item for item in report.employees if item.employee_id == employee_id), None)
    if mine is None:
        return None
    requests = await create_attendance_resolution_service().for_employee(employee_id)
    pending = sum(
        request.status is ResolutionStatus.PENDING
        and period.start <= request.work_date <= period.end
        for request in requests
    )
    await anyio.sleep(random.uniform(*_REPLY_DELAY_SECONDS))  # noqa: S311 - timing jitter only
    return (
        f"*Attendance — {period.label()}*\n\n"
        f"Perlu tindakan : {len(mine.log_1_pama_evidence_days)}\n"
        f"Menunggu PMO   : {pending}\n"
        f"Data belum masuk: {len(mine.log_1_pama_missing_data_days)}\n\n"
        "Lengkapi gap, evidence, dan pengajuan PMO dari card tanggalnya:\n"
        f"{url}\n\n"
        "Raw attendance client tetap tidak diubah."
    )


async def reply(text: str, jid: str) -> str:
    normalized = text.strip().casefold()
    if normalized not in _TASK_MOBILE_COMMANDS and normalized not in _ATTENDANCE_MOBILE_COMMANDS:
        return await workflow_reply(text, jid)

    employee_id = await create_activation_service().resolve(jid)
    if employee_id is None:
        # PMO, onboarding, rebind, and unknown senders remain entirely under
        # the existing DM workflow.
        return await workflow_reply(text, jid)

    period = _period()
    if normalized in _TASK_MOBILE_COMMANDS:
        mobile = await _task_mobile_reply(employee_id, jid, period)
    else:
        mobile = await _attendance_mobile_reply(employee_id, jid, period)
    return await workflow_reply(text, jid) if mobile is None else mobile


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
