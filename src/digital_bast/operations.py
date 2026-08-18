from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

from digital_bast.config import Settings, SettingsConfigurationError, get_settings
from digital_bast.domain.completion import CompletionReport, evaluate_completion
from digital_bast.infrastructure.completion_source import (
    NocoDBAttendanceReader,
    NocoDBCompletionSource,
    NocoDBTaskEvidenceReader,
    parse_attendance_mapping,
)
from digital_bast.infrastructure.nocodb_repository import NocoDBDomainRepository
from digital_bast.infrastructure.production_sources import NocoDBPostgresEmployeeSource
from digital_bast.web.csv_export import attendance_csv
from digital_bast.web.postgres_backend import PostgresWebBackend

if TYPE_CHECKING:
    from collections.abc import Mapping

    from digital_bast.domain.completion import DateRange, EmployeeFacts
    from digital_bast.web.contracts import AttendanceRow

_TEMPLATE_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "templates"
_BAST_TEMPLATE: Final = "bast.html"
_MISSING_NOCODB: Final = "NOCODB_DATABASE_DSN, NOCODB_BASE_ID"
_MISSING_APP_DSN: Final = "APP_DATABASE_DSN"
_INVALID_SETTINGS: Final = "application settings are invalid; check .env and the secret files"


def _settings() -> Settings:
    try:
        return get_settings()
    except (ValidationError, SettingsConfigurationError, OSError) as error:
        raise OperationConfigurationError(_INVALID_SETTINGS) from error


class OperationConfigurationError(RuntimeError):
    def __init__(self, missing: str) -> None:
        super().__init__(missing)
        self.missing: str = missing

    @override
    def __str__(self) -> str:
        return f"missing configuration for this command: {self.missing}"


def create_completion_source() -> NocoDBCompletionSource:
    settings = _settings()
    dsn = settings.nocodb_database_dsn
    base_id = settings.nocodb_base_id
    if dsn is None or base_id is None:
        raise OperationConfigurationError(_MISSING_NOCODB)
    secret = dsn.get_secret_value()
    mapping = parse_attendance_mapping(settings.nocodb_attendance_mapping)
    evidence_column = settings.nocodb_task_evidence_column
    return NocoDBCompletionSource(
        NocoDBPostgresEmployeeSource(secret, base_id),
        NocoDBDomainRepository(secret, base_id),
        NocoDBAttendanceReader(secret, base_id, mapping) if mapping is not None else None,
        NocoDBTaskEvidenceReader(secret, base_id, evidence_column) if evidence_column else None,
    )


def create_attendance_backend() -> PostgresWebBackend:
    settings = _settings()
    dsn = settings.database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return PostgresWebBackend(dsn.get_secret_value())


async def completion_status(
    period: DateRange,
    employee: str | None = None,
    source: NocoDBCompletionSource | None = None,
) -> CompletionReport:
    active = source if source is not None else create_completion_source()
    return evaluate_completion(period, await active.load(period, employee))


async def export_attendance(
    period: DateRange,
    employees: tuple[str, ...] = (),
    backend: PostgresWebBackend | None = None,
) -> tuple[str, int]:
    active = backend if backend is not None else create_attendance_backend()
    rows: tuple[AttendanceRow, ...] = await active.attendance(employees, period.start, period.end)
    return attendance_csv(rows), len(rows)


def render_bast(
    report: CompletionReport,
    facts: Mapping[str, EmployeeFacts],
    label: str,
    generated_at: datetime,
) -> str:
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIRECTORY),
        autoescape=select_autoescape(("html",)),
    )
    template = environment.get_template(_BAST_TEMPLATE)
    return template.render(report=report, facts=facts, label=label, generated_at=generated_at)


async def generate_bast(
    period: DateRange,
    label: str = "",
    source: NocoDBCompletionSource | None = None,
) -> tuple[str, CompletionReport]:
    active = source if source is not None else create_completion_source()
    facts = await active.load(period, None)
    report = evaluate_completion(period, facts)
    title = label or f"BAST {period.label()}"
    document = render_bast(
        report,
        {item.employee_id: item for item in facts},
        title,
        datetime.now(UTC),
    )
    return document, report
