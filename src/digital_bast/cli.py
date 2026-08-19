from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, assert_never

import anyio
from anyio.to_thread import run_sync

from digital_bast.bot.evidence import UploadOutcome, outstanding, select_by_caption, select_by_index
from digital_bast.bot.identity import ActivationOutcome
from digital_bast.bot.whatsapp import (
    HELP_REPLY,
    MISSING_PERIOD_REPLY,
    MISSING_REPORT_TYPE_REPLY,
    MUTATION_REPLY,
    BotCommand,
    Intent,
    format_completion,
    format_evidence_resume,
    format_system_status,
    parse_command,
)
from digital_bast.domain.completion import (
    CompletionReport,
    DateRange,
    InvalidDateRangeError,
    format_day,
)
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
    issue_activation_codes,
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
        case _:
            _write(bot_reply(args.text, jid=args.jid, channel=args.channel))


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


_ACTIVATION_PATTERN: Final = re.compile(r"(?i)^\s*aktivasi\s+(\S+)\s+(\S+)\s*$")
_ACTIVATION_HELP: Final = (
    "Nomor ini belum terhubung ke data karyawan.\n"
    "Kirim: `aktivasi <Employee ID> <kode aktivasi>`\n"
    "Contoh: `aktivasi MTG-TF/2026010382 AB12CD34`"
)
_ACTIVATION_OUTCOME_REPLY: Final = {
    ActivationOutcome.SUCCESS: (
        "Aktivasi berhasil! Kirim `evidence` untuk melihat Closed task "
        "yang belum ada evidence-nya."
    ),
    ActivationOutcome.INVALID_CODE: "Kode aktivasi salah. Coba lagi.",
    ActivationOutcome.LOCKED: "Terlalu banyak percobaan salah. Coba lagi setelah 15 menit.",
    ActivationOutcome.ALREADY_USED: (
        "Kode aktivasi ini sudah pernah dipakai. Hubungi admin untuk kode baru."
    ),
    ActivationOutcome.UNKNOWN_EMPLOYEE: "Employee ID tidak ditemukan.",
    ActivationOutcome.ALREADY_BOUND: "Employee ID ini sudah terhubung ke nomor WhatsApp lain.",
}
_BAST_REPORT_TYPE: Final = {"developer": "developer", "shifting": "iotoperation"}
_EVIDENCE_EMPTY_REPLY: Final = "Semua Closed task kamu sudah ada evidence-nya. \U0001f44d"
_EVIDENCE_SELECT_INVALID: Final = "Nomor tidak valid. Kirim `evidence` untuk melihat daftar ulang."
_DM_HELP_REPLY: Final = (
    "Kirim `evidence` untuk melihat Closed task yang belum ada evidence, "
    "lalu balas nomornya dan kirim foto/dokumen evidence-nya."
)
_UPLOAD_OUTCOME_REPLY: Final = {
    UploadOutcome.DUPLICATE: "Foto ini sudah pernah dikirim untuk task ini.",
    UploadOutcome.NOT_FOUND: "Task tidak ditemukan.",
    UploadOutcome.NOT_OWNED: "Task ini bukan milik kamu.",
    UploadOutcome.NOT_CLOSED: "Task ini belum Closed.",
    UploadOutcome.TOO_LARGE: "Ukuran file lebih dari 5 MB.",
    UploadOutcome.UNSUPPORTED_TYPE: "Format file tidak didukung. Kirim PNG, JPEG, atau WebP.",
}


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


def _dm_llm_pick(evidence: EvidenceService, employee_id: str, jid: str, text: str) -> str | None:
    interpreter = create_llm_interpreter()
    if interpreter is None:
        return None
    candidates = outstanding(anyio.run(evidence.list_candidates, employee_id))
    if not candidates:
        return None
    titles = tuple(candidate.title for candidate in candidates)
    choice = anyio.run(interpreter.choose_index, titles, text)
    if choice is None:
        return None
    picked = candidates[choice - 1]
    anyio.run(evidence.set_pending, jid, picked.task_source, picked.task_key)
    return f'Oke, dipilih: "{picked.title}". Kirim foto/dokumen evidence-nya sekarang.'


def _dm_reply(text: str, jid: str) -> str:
    activation = create_activation_service()
    employee_id = anyio.run(activation.resolve, jid)
    if employee_id is None:
        match = _ACTIVATION_PATTERN.match(text)
        if match is None:
            return _ACTIVATION_HELP
        result = anyio.run(activation.activate, jid, match[1], match[2].upper())
        return _ACTIVATION_OUTCOME_REPLY[result.outcome]
    evidence = create_evidence_service()
    lowered = text.strip().casefold()
    if "evidence" in lowered:
        candidates = outstanding(anyio.run(evidence.list_candidates, employee_id))
        return _format_evidence_list(candidates) if candidates else _EVIDENCE_EMPTY_REPLY
    if text.strip().isdigit():
        candidates = outstanding(anyio.run(evidence.list_candidates, employee_id))
        picked = select_by_index(candidates, text)
        if picked is None:
            return _EVIDENCE_SELECT_INVALID
        anyio.run(evidence.set_pending, jid, picked.task_source, picked.task_key)
        return f'Oke, dipilih: "{picked.title}". Kirim foto/dokumen evidence-nya sekarang.'
    picked_reply = _dm_llm_pick(evidence, employee_id, jid, text)
    return picked_reply if picked_reply is not None else _DM_HELP_REPLY


async def bot_evidence(jid: str, file_path: Path, caption: str) -> str:
    activation = create_activation_service()
    employee_id = await activation.resolve(jid)
    if employee_id is None:
        return _ACTIVATION_HELP
    evidence = create_evidence_service()
    candidates = outstanding(await evidence.list_candidates(employee_id))
    if not candidates:
        return _EVIDENCE_EMPTY_REPLY
    target = select_by_caption(candidates, caption) if caption.strip() else None
    if target is None:
        pending = await evidence.pending_task(jid)
        if pending is not None:
            target = next(
                (c for c in candidates if (c.task_source, c.task_key) == pending), None
            )
    if target is None and len(candidates) == 1:
        target = candidates[0]
    if target is None:
        return _format_evidence_list(candidates)
    image = await run_sync(file_path.read_bytes)
    result = await evidence.upload(
        employee_id, target.task_source, target.task_key, image, caption
    )
    if result.outcome is UploadOutcome.STORED:
        await evidence.clear_pending(jid)
        return f'Evidence untuk "{target.title}" tersimpan. Terima kasih!'
    return _UPLOAD_OUTCOME_REPLY[result.outcome]


def bot_reply(text: str, *, jid: str | None = None, channel: str = "group") -> str:
    if channel == "dm":
        return _dm_reply(text, jid) if jid else HELP_REPLY
    return _group_reply(text)


def _resolve_command(text: str, today: date) -> BotCommand:
    interpreter = create_llm_interpreter()
    if interpreter is not None:
        drafted = anyio.run(interpreter.interpret, text, today)
        if drafted is not None:
            return drafted
    return parse_command(text, today)


def _group_reply(text: str) -> str:
    command = _resolve_command(text, datetime.now(JAKARTA).date())
    match command.intent:
        case Intent.UNSUPPORTED_MUTATION:
            return MUTATION_REPLY
        case Intent.SYSTEM_STATUS:
            return format_system_status(system_status())
        case Intent.UNKNOWN:
            return HELP_REPLY
        case _:
            pass
    if command.period is None:
        return MISSING_PERIOD_REPLY
    if command.intent is Intent.EXPORT_ATTENDANCE and command.report_type is None:
        return MISSING_REPORT_TYPE_REPLY
    return _business_reply(command.intent, command.period, command.report_type)


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


def _business_reply(intent: Intent, period: DateRange, report_type: str | None) -> str:
    echo = _echo_interpretation(intent, period, report_type)
    match intent:
        case Intent.COMPLETION_STATUS:
            return f"{echo}\n\n" + format_completion(anyio.run(completion_status, period, None))
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
                        f"{echo}\nExport attendance {period.label()} "
                        f"({report_type}): {rows} baris."
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
