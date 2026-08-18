from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_never

import anyio
from prefect import serve

from digital_bast.bot.whatsapp import (
    HELP_REPLY,
    MISSING_PERIOD_REPLY,
    MUTATION_REPLY,
    Intent,
    format_completion,
    format_system_status,
    parse_command,
)
from digital_bast.domain.completion import (
    CompletionReport,
    DateRange,
    InvalidDateRangeError,
)
from digital_bast.domain.time import JAKARTA
from digital_bast.flows.deployments import build_deployments, deployment_schedules
from digital_bast.flows.models import InvalidPeriodError, Period, RunSummary
from digital_bast.flows.pipelines import (
    iot_pic_update_flow,
    monthly_timesheets_flow,
    nightly_reconciliation_flow,
    operational_import_flow,
    reference_data_flow,
)
from digital_bast.flows.runtime import (
    InvalidRunContextFactoryError,
    RunContextUnavailableError,
    use_run_context,
)
from digital_bast.infrastructure.docker_status import (
    DockerUnavailableError,
    SystemStatus,
    system_status,
)
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.operations import (
    OperationConfigurationError,
    completion_status,
    export_attendance,
    generate_bast,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from digital_bast.flows.contracts import RunContextFactory


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
    _ = bast_parser.add_argument("--label", default="")
    _ = bast_parser.add_argument("--output")
    status_parser = subparsers.add_parser("system-status")
    _ = status_parser.add_argument(
        "--format", dest="output_format", choices=("json", "text"), default="json"
    )
    bot_parser = subparsers.add_parser("bot-reply")
    _ = bot_parser.add_argument("--text", required=True)
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
    try:
        with use_run_context(context_factory) if context_factory is not None else nullcontext():
            return _dispatch(args)
    except (
        InvalidPeriodError,
        InvalidRunContextFactoryError,
        RunContextUnavailableError,
        InvalidDateRangeError,
        DockerUnavailableError,
        OperationConfigurationError,
        InfrastructureError,
    ) as error:
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
        ):
            _dispatch_command(args)
        case _:
            assert_never(args.command)
    return 0


def _dispatch_flow(args: CliArguments) -> None:
    match args.command:
        case "list":
            _print_deployments()
        case "serve":
            if args.dry_run:
                _print_deployments()
            else:
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
        case _:
            _write(bot_reply(args.text))


async def _run_flow(name: FlowName, period: str | None) -> RunSummary:
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
    document, report = anyio.run(generate_bast, period, args.label)
    target = Path(
        args.output
        or f"bast-{period.start.isoformat()}-{period.end.isoformat()}.html"
    )
    _ = target.write_text(document, encoding="utf-8")
    _write_json(
        {
            "employees": len(report.employees),
            "path": str(target),
            "start_date": period.start.isoformat(),
            "end_date": period.end.isoformat(),
            "state": report.state.value,
        }
    )


def _run_system_status(args: CliArguments) -> None:
    status = system_status()
    if args.output_format == "text":
        _write(format_system_status(status))
        return
    _write_json(status_payload(status))


def bot_reply(text: str) -> str:
    command = parse_command(text, datetime.now(JAKARTA).date())
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
    return _business_reply(command.intent, command.period)


def _business_reply(intent: Intent, period: DateRange) -> str:
    match intent:
        case Intent.COMPLETION_STATUS:
            return format_completion(anyio.run(completion_status, period, None))
        case Intent.EXPORT_ATTENDANCE:
            _, rows = anyio.run(export_attendance, period, ())
            return (
                f"Export attendance {period.label()} siap: {rows} baris. "
                "Jalankan `digital-bast export-attendance --output` untuk mengunduh berkas CSV."
            )
        case _:
            document, report = anyio.run(generate_bast, period, "")
            return (
                f"BAST {period.label()} dibuat ({len(document)} karakter, "
                f"status {report.state.value})."
            )


def _print_deployments() -> None:
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
