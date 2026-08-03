from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from dataclasses import asdict
from typing import TYPE_CHECKING, Literal, assert_never

import anyio
from prefect import serve

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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from digital_bast.flows.contracts import RunContextFactory


type Command = Literal["list", "serve", "backfill-timesheets", "run"]
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
    ) as error:
        _ = sys.stderr.write(f"{error}\n")
        return 2


def _dispatch(args: CliArguments) -> int:
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
            assert_never(args.command)
    return 0


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
