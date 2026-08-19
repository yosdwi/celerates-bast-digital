from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, assert_never

import anyio
from anyio.to_thread import run_sync

from digital_bast.bot.evidence import (
    UploadOutcome,
    outstanding,
    select_by_caption_all,
    select_by_index,
    sniff_content_type,
)
from digital_bast.bot.identity import ActivationOutcome, resolve_employee_by_nrp
from digital_bast.bot.whatsapp import (
    HELP_REPLY,
    MISSING_PERIOD_REPLY,
    MISSING_REPORT_TYPE_REPLY,
    MUTATION_REPLY,
    PERSONA_FALLBACK_REPLY,
    BotCommand,
    Intent,
    extract_index,
    format_completion,
    format_employee_detail,
    format_evidence_resume,
    format_system_status,
    parse_command,
    parse_period,
    strip_mentions,
)
from digital_bast.domain.completion import (
    CheckState,
    CompletionReport,
    DateRange,
    EmployeeCompletion,
    InvalidDateRangeError,
    format_day,
)
from digital_bast.domain.identity import canonical_text
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.docker_status import (
    DockerUnavailableError,
    SystemStatus,
    system_status,
)
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.operations import (
    OperationConfigurationError,
    completion_status,
    create_activation_service,
    create_evidence_service,
    create_llm_interpreter,
    export_attendance,
    export_attendance_report,
    generate_bast,
    generate_status_matrix,
    issue_activation_codes,
    load_roster,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from digital_bast.bot.evidence import EvidenceCandidate, EvidenceService
    from digital_bast.flows.contracts import RunContextFactory
    from digital_bast.flows.models import RunSummary

_FLOW_COMMANDS: Final = frozenset({"list", "serve", "backfill-timesheets", "run"})


type Command = Literal[
    "list",
    "serve",
    "backfill-timesheets",
    "run",
    "completion-status",
    "export-attendance",
    "generate-bast",
    "system-status",
    "bot-reply",
    "issue-activation-codes",
    "bot-evidence",
    "reset-identity",
]
type FlowName = Literal[
    "operational-import",
    "nightly-reconciliation",
    "reference-data",
    "monthly-timesheets",
    "iot-pic-update",
]


class CliArguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.command: Command = "list"
        self.dry_run: bool = False
        self.flow: FlowName = "operational-import"
        self.period: str | None = None
        self.start_date: date = date.min
        self.end_date: date = date.min
        self.employee: str | None = None
        self.label: str = ""
        self.output: str | None = None
        self.output_format: str = "json"
        self.text: str = ""
        self.jid: str | None = None
        self.channel: str = "group"
        self.file: str = ""
        self.caption: str = ""
        self.report_type: str = "developer"
        self.nrp: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digital-bast")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _ = subparsers.add_parser("list")
    serve_parser = subparsers.add_parser("serve")
    _ = serve_parser.add_argument("--dry-run", action="store_true")
    run_parser = subparsers.add_parser("run")
    _ = run_parser.add_argument(
        "flow",
        choices=(
            "operational-import",
            "nightly-reconciliation",
            "reference-data",
            "monthly-timesheets",
            "iot-pic-update",
        ),
    )
    _ = run_parser.add_argument("--period")
    _ = run_parser.add_argument("--dry-run", action="store_true")
    backfill_parser = subparsers.add_parser("backfill-timesheets")
    _ = backfill_parser.add_argument("--period", required=True)
    _ = backfill_parser.add_argument("--dry-run", action="store_true")
    completion_parser = _with_range(subparsers.add_parser("completion-status"))
    _ = completion_parser.add_argument("--employee")
    _ = completion_parser.add_argument(
        "--format", dest="output_format", choices=("json", "text"), default="json"
    )
    export_parser = _with_range(subparsers.add_parser("export-attendance"))
    _ = export_parser.add_argument("--employee", action="append", dest="employees", default=[])
    _ = export_parser.add_argument("--label", default="")
    _ = export_parser.add_argument("--output")
    bast_parser = _with_range(subparsers.add_parser("generate-bast"))
    _ = bast_parser.add_argument(
        "--type", dest="report_type", choices=("developer", "iotoperation"), default="developer"
    )
    _ = bast_parser.add_argument("--output")
    status_parser = subparsers.add_parser("system-status")
    _ = status_parser.add_argument(
        "--format", dest="output_format", choices=("json", "text"), default="json"
    )
    bot_parser = subparsers.add_parser("bot-reply")
    _ = bot_parser.add_argument("--text", required=True)
    _ = bot_parser.add_argument("--jid", default=None)
    _ = bot_parser.add_argument("--channel", choices=("group", "dm"), default="group")
    _ = subparsers.add_parser("issue-activation-codes")
    evidence_parser = subparsers.add_parser("bot-evidence")
    _ = evidence_parser.add_argument("--jid", required=True)
    _ = evidence_parser.add_argument("--file", required=True)
    _ = evidence_parser.add_argument("--caption", default="")
    reset_parser = subparsers.add_parser("reset-identity")
    target = reset_parser.add_mutually_exclusive_group(required=True)
    _ = target.add_argument("--nrp")
    _ = target.add_argument("--jid")
    return parser


def _with_range(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    _ = parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    _ = parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    return parser


def main(
    argv: Sequence[str] | None = None,
    context_factory: RunContextFactory | None = None,
) -> int:
    args = build_parser().parse_args(argv, namespace=CliArguments())
    exceptions: tuple[type[Exception], ...] = (
        InvalidDateRangeError,
        DockerUnavailableError,
        OperationConfigurationError,
        InfrastructureError,
    )
    context_manager = nullcontext()
    # local: flows.models/flows.runtime pull in the flows package, which eagerly
    # imports Prefect (slow in this environment). Command-dispatch (bot-reply,
    # export-attendance, ...) never touches flows, so keep this import off that
    # path entirely -- it's the dominant cost in the bot's reply latency.
    if args.command in _FLOW_COMMANDS or context_factory is not None:
        from digital_bast.flows.models import InvalidPeriodError  # noqa: PLC0415
        from digital_bast.flows.runtime import (  # noqa: PLC0415
            InvalidRunContextFactoryError,
            RunContextUnavailableError,
            use_run_context,
        )

        exceptions = (
            InvalidPeriodError,
            InvalidRunContextFactoryError,
            RunContextUnavailableError,
            *exceptions,
        )
        if context_factory is not None:
            context_manager = use_run_context(context_factory)
    try:
        with context_manager:
            return _dispatch(args)
    except exceptions as error:
        _ = sys.stderr.write(f"{error}\n")
        return 2


def _dispatch(args: CliArguments) -> int:
    match args.command:
        case "list" | "serve" | "backfill-timesheets" | "run":
            _dispatch_flow(args)
        case (
            "completion-status"
            | "export-attendance"
            | "generate-bast"
            | "system-status"
            | "bot-reply"
            | "issue-activation-codes"
            | "bot-evidence"
            | "reset-identity"
        ):
            _dispatch_command(args)
        case _:
            assert_never(args.command)
    return 0


def _dispatch_flow(args: CliArguments) -> None:
    from digital_bast.flows.models import InvalidPeriodError, Period  # noqa: PLC0415

    match args.command:
        case "list":
            _print_deployments()
        case "serve":
            if args.dry_run:
                _print_deployments()
            else:
                # local: flows.deployments pulls in Prefect, which is slow to import
                # and only needed by flow-dispatch commands, never by bot-reply.
                from prefect import serve  # noqa: PLC0415

                from digital_bast.flows.deployments import build_deployments  # noqa: PLC0415

                serve(*build_deployments())
        case "backfill-timesheets":
            if args.period is None:
                missing_period = ""
                raise InvalidPeriodError(missing_period)
            period = str(Period.parse(args.period))
            if args.dry_run:
                _print_plan("monthly-timesheets", period)
            else:
                _print_summary(anyio.run(_run_flow, "monthly-timesheets", period))
        case "run":
            period = str(Period.parse(args.period)) if args.period is not None else None
            if args.dry_run:
                _print_plan(args.flow, period)
            else:
                _print_summary(anyio.run(_run_flow, args.flow, period))
        case _:
            pass


def _dispatch_command(args: CliArguments) -> None:
    match args.command:
        case "completion-status":
            _run_completion_status(args)
        case "export-attendance":
            _run_export_attendance(args)
        case "generate-bast":
            _run_generate_bast(args)
        case "system-status":
            _run_system_status(args)
        case "issue-activation-codes":
            _write_json(anyio.run(issue_activation_codes))
        case "bot-evidence":
            _write(anyio.run(bot_evidence, args.jid or "", Path(args.file), args.caption))
        case "reset-identity":
            _write_json(anyio.run(_run_reset_identity, args.nrp, args.jid))
        case _:
            _write(bot_reply(args.text, jid=args.jid, channel=args.channel))


async def _run_reset_identity(nrp: str | None, jid: str | None) -> dict[str, bool | str]:
    activation = create_activation_service()
    if jid is not None:
        removed = await activation.unbind_jid(jid)
        return {"jid": jid, "removed": removed}
    roster = await load_roster()
    employee = resolve_employee_by_nrp(nrp or "", roster)
    if employee is None:
        return {"nrp": nrp or "", "removed": False, "error": "NRP tidak ditemukan"}
    removed = await activation.unbind(str(employee.id))
    return {"nrp": nrp or "", "employee": employee.name, "removed": removed}


async def _run_flow(name: FlowName, period: str | None) -> RunSummary:
    # local: flows.pipelines pulls in Prefect; keep it off bot-reply's import path.
    from digital_bast.flows.pipelines import (  # noqa: PLC0415
        iot_pic_update_flow,
        monthly_timesheets_flow,
        nightly_reconciliation_flow,
        operational_import_flow,
        reference_data_flow,
    )

    match name:
        case "operational-import":
            return await operational_import_flow(period=period)
        case "nightly-reconciliation":
            return await nightly_reconciliation_flow(period=period)
        case "reference-data":
            return await reference_data_flow(period=period)
        case "monthly-timesheets":
            return await monthly_timesheets_flow(period=period)
        case "iot-pic-update":
            return await iot_pic_update_flow()
        case _:
            assert_never(name)


def _write(text: str) -> None:
    _ = sys.stdout.write(f"{text}\n")


def _write_json(payload: object) -> None:
    _write(json.dumps(payload, sort_keys=True))


def _selected_range(args: CliArguments) -> DateRange:
    return DateRange(args.start_date, args.end_date)


def completion_payload(report: CompletionReport) -> dict[str, object]:
    return {
        "start_date": report.period.start.isoformat(),
        "end_date": report.period.end.isoformat(),
        "state": report.state.value,
        "employees": [
            {
                "employee_id": employee.employee_id,
                "name": employee.name,
                "timesheet": {
                    "state": employee.timesheet.state.value,
                    "issues": list(employee.timesheet.issues),
                },
                "task_list": {
                    "state": employee.task_list.state.value,
                    "issues": list(employee.task_list.issues),
                },
                "evidence": {
                    "state": employee.evidence.state.value,
                    "issues": list(employee.evidence.issues),
                },
                "log_1_pama": {
                    "state": employee.log_1_pama.state.value,
                    "issues": list(employee.log_1_pama.issues),
                },
            }
            for employee in report.employees
        ],
    }


def status_payload(status: SystemStatus) -> dict[str, object]:
    return {
        "overall": status.overall,
        "services": [
            {"service": item.service, "state": item.state, "health": item.health}
            for item in status.services
        ],
    }


def _run_completion_status(args: CliArguments) -> None:
    report = anyio.run(completion_status, _selected_range(args), args.employee)
    if args.output_format == "text":
        _write(format_completion(report))
        return
    _write_json(completion_payload(report))


def _run_export_attendance(args: CliArguments) -> None:
    employees: tuple[str, ...] = tuple(getattr(args, "employees", ()) or ())
    content, rows = anyio.run(export_attendance, _selected_range(args), employees)
    if args.output is None:
        _ = sys.stdout.write(content)
        return
    path = Path(args.output)
    _ = path.write_text(content, encoding="utf-8", newline="")
    _write_json(
        {
            "label": args.label,
            "path": str(path),
            "rows": rows,
            "start_date": args.start_date.isoformat(),
            "end_date": args.end_date.isoformat(),
        }
    )


def _run_generate_bast(args: CliArguments) -> None:
    period = _selected_range(args)
    path, report = anyio.run(generate_bast, period, args.report_type)
    if args.output is not None:
        target = Path(args.output)
        _ = target.write_bytes(path.read_bytes())
        path = target
    _write_json(
        {
            "path": str(path),
            "report_type": report.report_type,
            "year": report.year,
            "month": report.month,
            "fingerprint": report.fingerprint,
        }
    )


def _run_system_status(args: CliArguments) -> None:
    status = system_status()
    if args.output_format == "text":
        _write(format_system_status(status))
        return
    _write_json(status_payload(status))


_BAST_REPORT_TYPE: Final = {"developer": "developer", "shifting": "iotoperation"}
_EVIDENCE_EMPTY_REPLY: Final = "Semua Closed task kamu sudah ada evidence-nya. \U0001f44d"
_EVIDENCE_SELECT_INVALID: Final = "Nomor tidak valid. Kirim `evidence` untuk melihat daftar ulang."
_DM_HELP_REPLY: Final = (
    "Kirim `evidence` untuk melihat Closed task yang belum ada evidence, "
    "lalu balas nomornya (atau nama task-nya) dan kirim foto/dokumen evidence-nya."
)
_UPLOAD_OUTCOME_REPLY: Final = {
    UploadOutcome.DUPLICATE: "Foto ini sudah pernah dikirim untuk task ini.",
    UploadOutcome.NOT_FOUND: "Task tidak ditemukan.",
    UploadOutcome.NOT_OWNED: "Task ini bukan milik kamu.",
    UploadOutcome.NOT_CLOSED: "Task ini belum Closed.",
    UploadOutcome.TOO_LARGE: "Ukuran file lebih dari 5 MB.",
    UploadOutcome.UNSUPPORTED_TYPE: "Format file tidak didukung. Kirim PNG, JPEG, atau WebP.",
}
# NRP-based onboarding (§1): talent know their NRP and name, never the
# internal Employee ID -- that stays purely an internal key from here on.
_NRP_HELP: Final = "Aku belum tahu kamu siapa.\nKirim NRP kamu ya."
_CONFIRM_CANCELLED: Final = "Oke, dibatalkan. Kirim NRP kamu lagi ya."
_CONFIRM_RETRY: Final = "Balas YA atau BUKAN ya."
_ALREADY_BOUND_ELSEWHERE: Final = (
    "NRP ini sudah terhubung ke nomor WhatsApp lain. Hubungi admin untuk reset."
)
_YES_WORDS: Final = frozenset({"ya", "iya", "yes", "y", "betul", "benar", "yoi", "bener"})
_NO_WORDS: Final = frozenset({"bukan", "tidak", "no", "salah", "nggak", "gak", "ga"})
_SUMMARY_WORDS: Final = ("tasklist", "task list", "kurang", "progress", "evidence")
_MIN_AMBIGUOUS_MATCHES: Final = 2


def _confirm_prompt(name: str, nrp: str) -> str:
    return f"Aku menemukan:\n{name}\nNRP: {nrp}\n\nIni kamu?\nBalas YA atau BUKAN."


def _bound_reply(name: str) -> str:
    return f"✅ Terhubung sebagai {name}."


async def _dm_onboarding(text: str, jid: str) -> str:
    activation = create_activation_service()
    pending_employee_id = await activation.pending_claim(jid)
    lowered = text.strip().casefold()
    if pending_employee_id is not None:
        if lowered in _YES_WORDS:
            outcome = await activation.bind(jid, pending_employee_id)
            await activation.clear_claim(jid)
            if outcome is not ActivationOutcome.SUCCESS:
                return _ALREADY_BOUND_ELSEWHERE
            roster = await load_roster()
            name = next(
                (e.name for e in roster if str(e.id) == pending_employee_id), pending_employee_id
            )
            return _bound_reply(name)
        if lowered in _NO_WORDS:
            await activation.clear_claim(jid)
            return _CONFIRM_CANCELLED
        return _CONFIRM_RETRY
    roster = await load_roster()
    employee = resolve_employee_by_nrp(text, roster)
    if employee is None:
        return _NRP_HELP
    await activation.claim(jid, str(employee.id))
    return _confirm_prompt(employee.name, employee.external_id)


def _format_evidence_list(candidates: tuple[EvidenceCandidate, ...]) -> str:
    lines = ["*Closed task tanpa evidence*", ""]
    lines.extend(
        f"{index}. {candidate.title} ({format_day(candidate.work_date)})"
        for index, candidate in enumerate(candidates, start=1)
    )
    lines.append("")
    lines.append("Balas nomornya, lalu kirim foto/dokumen evidence-nya.")
    lines.append(
        "Tips: kirim sebagai *Dokumen* (bukan Foto) supaya kualitas gambar tidak dikompres "
        "WhatsApp."
    )
    return "\n".join(lines)


def _format_ambiguous_choice(matches: tuple[EvidenceCandidate, ...]) -> str:
    lines = [f"Aku menemukan {len(matches)} task yang cocok:", ""]
    lines.extend(f"{index}. {c.title}" for index, c in enumerate(matches, start=1))
    lines.append("")
    lines.append("Foto ini untuk yang mana? Balas nomornya.")
    return "\n".join(lines)


def _format_upload_success(
    title: str, remaining: tuple[EvidenceCandidate, ...], done: int, total: int
) -> str:
    if not remaining:
        return f"✅ Evidence tersimpan.\n\nEvidence kamu sekarang lengkap: {done}/{total}."
    lines = [
        "✅ Evidence tersimpan untuk:",
        "",
        title,
        "",
        f"Progress Evidence kamu: {done}/{total} Closed Task lengkap.",
        "",
        "Masih kurang:",
    ]
    lines.extend(f"• {c.title}" for c in remaining)
    return "\n".join(lines)


async def _complete_upload(  # noqa: PLR0913, PLR0917
    evidence: EvidenceService,
    employee_id: str,
    jid: str,
    target: EvidenceCandidate,
    image: bytes,
    caption: str,
) -> str:
    result = await evidence.upload(employee_id, target.task_key, image, caption)
    if result.outcome is not UploadOutcome.STORED:
        return _UPLOAD_OUTCOME_REPLY[result.outcome]
    await evidence.clear_pending(jid)
    all_closed = await evidence.list_candidates(employee_id)
    remaining = outstanding(all_closed)
    done = len(all_closed) - len(remaining)
    return _format_upload_success(target.title, remaining, done, len(all_closed))


async def _format_personal_summary(
    employee_id: str, period: DateRange, evidence: EvidenceService
) -> str:
    report = await completion_status(period)
    mine = next((e for e in report.employees if e.employee_id == employee_id), None)
    candidates = outstanding(await evidence.list_candidates(employee_id))
    total = 0
    not_closed = 0
    if mine is not None:
        total = mine.total_tasks
        # task_list.issues holds one NO_TASKS_ISSUE sentinel (state
        # NEEDS_REVIEW) when the employee has zero tasks at all -- that's
        # not a "not closed" task, only count issues when the check
        # actually failed.
        if mine.task_list.state is CheckState.INCOMPLETE:
            not_closed = len(mine.task_list.issues)
    closed = max(total - not_closed, 0)
    lines = [
        f"*Task List kamu — {period.label()}*",
        "",
        f"Total        : {total}",
        f"Closed       : {closed}",
        f"Belum Closed : {not_closed}",
    ]
    if candidates:
        lines.append(f"Evidence     : {len(candidates)} Closed task belum ada evidence")
        lines.append("")
        lines.append("Belum ada evidence:")
        lines.extend(f"{index}. {c.title}" for index, c in enumerate(candidates, start=1))
        lines.append("")
        lines.append('Kirim foto dengan caption seperti:\n"buat poin 1" atau "buat CCTV".')
    else:
        lines.append("Evidence     : lengkap ✅")
    return "\n".join(lines).strip()


async def _pick_task(
    evidence: EvidenceService, employee_id: str, jid: str, picked: EvidenceCandidate
) -> str:
    stashed = await evidence.stashed_image(jid)
    if stashed is not None:
        image, _content_type, caption = stashed
        await evidence.clear_stashed_image(jid)
        return await _complete_upload(evidence, employee_id, jid, picked, image, caption)
    await evidence.set_pending(jid, picked.task_key)
    return f'Oke, dipilih: "{picked.title}". Kirim foto/dokumen evidence-nya sekarang.'


async def _dm_llm_pick(
    evidence: EvidenceService, employee_id: str, jid: str, text: str
) -> str | None:
    interpreter = create_llm_interpreter()
    if interpreter is None:
        return None
    candidates = outstanding(await evidence.list_candidates(employee_id))
    if not candidates:
        return None
    titles = tuple(candidate.title for candidate in candidates)
    choice = await interpreter.choose_index(titles, text)
    if choice is None or not 1 <= choice <= len(candidates):
        return None
    return await _pick_task(evidence, employee_id, jid, candidates[choice - 1])


async def _dm_reply(text: str, jid: str) -> str:  # noqa: C901, PLR0911 -- a resolution priority chain
    activation = create_activation_service()
    employee_id = await activation.resolve(jid)
    if employee_id is None:
        return await _dm_onboarding(text, jid)
    evidence = create_evidence_service()
    normalized = strip_mentions(text)
    lowered = normalized.strip().casefold()
    if not lowered:
        return _DM_HELP_REPLY
    if any(word in lowered for word in _SUMMARY_WORDS):
        today = datetime.now(JAKARTA).date()
        period = parse_period(normalized, today) or DateRange(today.replace(day=1), today)
        return await _format_personal_summary(employee_id, period, evidence)
    index = extract_index(normalized)
    if index is not None:
        # An explicit index may refer to the narrowed subset shown by a prior
        # ambiguous-photo clarification (§5), not the full outstanding list --
        # reconstruct that same subset from the stashed caption if present.
        candidates = outstanding(await evidence.list_candidates(employee_id))
        stashed = await evidence.stashed_image(jid)
        pool = candidates
        if stashed is not None:
            _, _, stashed_caption = stashed
            if stashed_caption.strip():
                narrowed = select_by_caption_all(candidates, stashed_caption)
                if len(narrowed) >= _MIN_AMBIGUOUS_MATCHES:
                    pool = narrowed
        picked = select_by_index(pool, str(index))
        if picked is None:
            return _EVIDENCE_SELECT_INVALID
        return await _pick_task(evidence, employee_id, jid, picked)
    candidates = outstanding(await evidence.list_candidates(employee_id))
    narrowed = select_by_caption_all(candidates, normalized)
    if len(narrowed) == 1:
        return await _pick_task(evidence, employee_id, jid, narrowed[0])
    if len(narrowed) >= _MIN_AMBIGUOUS_MATCHES:
        return _format_ambiguous_choice(narrowed)
    picked_reply = await _dm_llm_pick(evidence, employee_id, jid, normalized)
    return picked_reply if picked_reply is not None else _DM_HELP_REPLY


async def _resolve_evidence_target(  # noqa: C901 -- a sequential priority chain, not nested branching
    evidence: EvidenceService,
    candidates: tuple[EvidenceCandidate, ...],
    jid: str,
    caption: str,
) -> tuple[EvidenceCandidate | None, tuple[EvidenceCandidate, ...]]:
    """Resolution priority (§4): explicit index > natural-language reference
    (exact substring, then LLM-bounded) > pending-task state > single
    candidate. Returns (target, narrowed) -- narrowed is the substring-match
    subset when that's what made it ambiguous, for the clarifying question.
    """
    index = extract_index(caption)
    if index is not None:
        target = select_by_index(candidates, str(index))
        if target is not None:
            return target, ()

    narrowed: tuple[EvidenceCandidate, ...] = ()
    if caption.strip():
        narrowed = select_by_caption_all(candidates, caption)
        if len(narrowed) == 1:
            return narrowed[0], ()
    if caption.strip() and not narrowed:
        interpreter = create_llm_interpreter()
        if interpreter is not None:
            titles = tuple(c.title for c in candidates)
            choice = await interpreter.choose_index(titles, caption)
            if choice is not None and 1 <= choice <= len(candidates):
                return candidates[choice - 1], ()

    pending = await evidence.pending_task(jid)
    if pending is not None:
        target = next((c for c in candidates if (c.task_source, c.task_key) == pending), None)
        if target is not None:
            return target, ()

    if len(candidates) == 1:
        return candidates[0], ()
    return None, narrowed


async def bot_evidence(jid: str, file_path: Path, caption: str) -> str:
    activation = create_activation_service()
    employee_id = await activation.resolve(jid)
    if employee_id is None:
        return _NRP_HELP
    evidence = create_evidence_service()
    candidates = outstanding(await evidence.list_candidates(employee_id))
    if not candidates:
        return _EVIDENCE_EMPTY_REPLY
    image = await run_sync(file_path.read_bytes)
    content_type = sniff_content_type(image) or "image/jpeg"

    target, narrowed = await _resolve_evidence_target(evidence, candidates, jid, caption)
    if target is None:
        # §5: don't make the user resend the photo -- stash it, scoped to
        # this sender, and consume it from _dm_reply/_pick_task once they
        # answer the clarifying question.
        await evidence.stash_image(jid, image, content_type, caption)
        if len(narrowed) >= _MIN_AMBIGUOUS_MATCHES:
            return _format_ambiguous_choice(narrowed)
        return _format_evidence_list(candidates)

    return await _complete_upload(evidence, employee_id, jid, target, image, caption)


def bot_reply(text: str, *, jid: str | None = None, channel: str = "group") -> str:
    if channel == "dm":
        return anyio.run(_dm_reply, text, jid) if jid else HELP_REPLY
    return _group_reply(text)


def _resolve_command(text: str, today: date) -> BotCommand:
    normalized = strip_mentions(text)
    interpreter = create_llm_interpreter()
    if interpreter is not None:
        drafted = anyio.run(interpreter.interpret, normalized, today)
        if drafted is not None:
            return drafted
    return parse_command(normalized, today)


def _persona_reply(text: str) -> str:
    interpreter = create_llm_interpreter()
    if interpreter is not None:
        reply = anyio.run(interpreter.persona_reply, strip_mentions(text))
        if reply:
            return reply
    return PERSONA_FALLBACK_REPLY


def _group_reply(text: str) -> str:  # noqa: PLR0911 -- one short-circuit per intent case
    today = datetime.now(JAKARTA).date()
    # Deterministic fast-path: an unambiguous greeting/intro/capability
    # keyword ("kenalin", "siapa kamu", "makasih", ...) needs no LLM
    # round-trip at all -- skip straight to the static reply instead of
    # waiting 10-40s on this hardware for wording the keyword already
    # answers. parse_command() checks every business keyword first (see
    # whatsapp.py::_INTENT_RULES), so this can never mask a real business
    # request as conversation. Anything NOT keyword-matched still goes
    # through the normal LLM-primary path below (rare free-form smalltalk).
    if parse_command(strip_mentions(text), today).intent is Intent.CONVERSATION:
        return PERSONA_FALLBACK_REPLY
    command = _resolve_command(text, today)
    match command.intent:
        case Intent.UNSUPPORTED_MUTATION:
            return MUTATION_REPLY
        case Intent.SYSTEM_STATUS:
            return format_system_status(system_status())
        case Intent.CONVERSATION:
            return _persona_reply(text)
        case Intent.UNKNOWN:
            return HELP_REPLY
        case _:
            pass
    if command.period is None:
        return MISSING_PERIOD_REPLY
    if command.intent is Intent.EXPORT_ATTENDANCE and command.report_type is None:
        return MISSING_REPORT_TYPE_REPLY
    return _business_reply(command.intent, command.period, command.report_type, command.employee)


def _echo_interpretation(intent: Intent, period: DateRange, report_type: str | None) -> str:
    match intent:
        case Intent.EXPORT_ATTENDANCE:
            body = f"export attendance {report_type}, {period.label()}"
        case Intent.COMPLETION_STATUS:
            body = f"status {period.label()}"
        case Intent.EVIDENCE_RESUME:
            body = f"evidence {period.label()}"
        case _:
            body = f"generate bast {report_type or 'developer'}, {period.label()}"
    return f"Saya baca sebagai: {body}."


def _select_by_name(report: CompletionReport, employee: str) -> tuple[EmployeeCompletion, ...]:
    needle = canonical_text(employee)
    return tuple(e for e in report.employees if needle in canonical_text(e.name))


def _employee_detail_reply(period: DateRange, employee: str) -> str:
    report = anyio.run(completion_status, period, None)
    matches = _select_by_name(report, employee)
    if not matches:
        return f'Talent "{employee}" tidak ditemukan pada periode {period.label()}.'
    if len(matches) > 1:
        names = "\n".join(f"• {m.name}" for m in matches)
        return (
            f'Ada {len(matches)} talent yang cocok dengan "{employee}":\n\n{names}\n\n'
            "Sebutkan nama lengkapnya ya."
        )
    return format_employee_detail(next(iter(matches)), period)


def _business_reply(
    intent: Intent, period: DateRange, report_type: str | None, employee: str | None = None
) -> str:
    echo = _echo_interpretation(intent, period, report_type)
    match intent:
        case Intent.COMPLETION_STATUS if employee:
            return _employee_detail_reply(period, employee)
        case Intent.COMPLETION_STATUS:
            report = anyio.run(completion_status, period, None)
            path = anyio.run(generate_status_matrix, period)
            return json.dumps(
                {
                    "kind": "file",
                    "path": str(path),
                    "filename": path.name,
                    "caption": f"{echo}\n\n{format_completion(report)}",
                }
            )
        case Intent.EVIDENCE_RESUME:
            report = anyio.run(completion_status, period, None)
            return f"{echo}\n\n" + format_evidence_resume(report)
        case Intent.EXPORT_ATTENDANCE:
            if report_type is None:
                return MISSING_REPORT_TYPE_REPLY
            path, rows = anyio.run(export_attendance_report, period, report_type)
            return json.dumps(
                {
                    "kind": "file",
                    "path": str(path),
                    "filename": path.name,
                    "caption": (
                        f"{echo}\nExport attendance {period.label()} ({report_type}): {rows} baris."
                    ),
                }
            )
        case _:
            resolved_type = _BAST_REPORT_TYPE.get(report_type or "", "developer")
            path, report = anyio.run(generate_bast, period, resolved_type)
            return json.dumps(
                {
                    "kind": "file",
                    "path": str(path),
                    "filename": path.name,
                    "caption": (
                        f"{echo}\nBAST {report.report_type} {period.label()} berhasil digenerate."
                    ),
                }
            )


def _print_deployments() -> None:
    from digital_bast.flows.deployments import deployment_schedules  # noqa: PLC0415

    payload = [
        {
            "concurrency_limit": schedule.concurrency_limit,
            "cron": schedule.cron,
            "name": schedule.name,
            "timezone": schedule.timezone,
        }
        for schedule in deployment_schedules()
    ]
    _ = sys.stdout.write(f"{json.dumps(payload, sort_keys=True)}\n")


def _print_plan(name: str, period: str | None) -> None:
    payload = {"dry_run": True, "flow": name, "period": period}
    _ = sys.stdout.write(f"{json.dumps(payload, sort_keys=True)}\n")


def _print_summary(summary: RunSummary) -> None:
    payload = asdict(summary)
    payload["period"] = str(summary.period)
    _ = sys.stdout.write(f"{json.dumps(payload, sort_keys=True)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
