from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from pydantic import ValidationError

from digital_bast.bot.evidence import EvidenceService
from digital_bast.bot.identity import ActivationService
from digital_bast.bot.llm import LlmInterpreter
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

if TYPE_CHECKING:
    from digital_bast.domain.completion import DateRange
    from digital_bast.domain.models import Employee
    from digital_bast.web.bast_assembler import AssembledReport
    from digital_bast.web.contracts import AttendanceRow
    from digital_bast.web.postgres_backend import PostgresWebBackend

_EXPORTS_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "bot-bridge" / "data" / "exports"
_LOCAL_EMPLOYEE_FILE: Final = Path(__file__).resolve().parents[2] / "employee_data.json"
_REPORT_TYPE_ROLE: Final = {"developer": "Developer", "shifting": "IoT Operations"}
_REPORT_TYPE_SUFFIX: Final = {"developer": "DEVELOPER", "shifting": "SHIFTING"}
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


def create_local_completion_source() -> NocoDBCompletionSource:
    # local: NocoDB is unreachable; fall back to durable_records + the flat
    # attendance rows scripts/load_pama_attendance.py already writes there.
    # Evidence comes from task_evidence (talent uploads over WhatsApp DM,
    # see bot/evidence.py) -- per-task, unlike the old NocoDB aggregate.
    from digital_bast.infrastructure.local_completion_source import (  # noqa: PLC0415
        LocalEmployeeSource,
        PostgresAttendanceFactReader,
        PostgresTaskEvidenceReader,
    )
    from digital_bast.infrastructure.repositories import PostgresDomainRepository  # noqa: PLC0415

    settings = _settings()
    dsn = settings.database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    secret = dsn.get_secret_value()
    return NocoDBCompletionSource(
        LocalEmployeeSource(_LOCAL_EMPLOYEE_FILE),
        PostgresDomainRepository(secret),
        PostgresAttendanceFactReader(secret),
        PostgresTaskEvidenceReader(secret),
    )


def create_attendance_backend() -> PostgresWebBackend:
    # local: digital_bast.web's package init pulls in the full FastAPI app,
    # redis, etc. -- keep that off commands that never touch attendance export.
    from digital_bast.web.postgres_backend import PostgresWebBackend  # noqa: PLC0415

    settings = _settings()
    dsn = settings.database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return PostgresWebBackend(dsn.get_secret_value())


def create_activation_service() -> ActivationService:
    settings = _settings()
    dsn = settings.database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return ActivationService(dsn.get_secret_value())


def create_evidence_service() -> EvidenceService:
    settings = _settings()
    dsn = settings.database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return EvidenceService(dsn.get_secret_value())


def create_llm_interpreter() -> LlmInterpreter | None:
    settings = _settings()
    if settings.bot_llm_url is None:
        return None
    return LlmInterpreter(str(settings.bot_llm_url), settings.bot_llm_model)


async def load_roster() -> tuple[Employee, ...]:
    from digital_bast.infrastructure.local_completion_source import (  # noqa: PLC0415
        LocalEmployeeSource,
    )

    return await LocalEmployeeSource(_LOCAL_EMPLOYEE_FILE).load()


async def issue_activation_codes(service: ActivationService | None = None) -> dict[str, str]:
    active = service if service is not None else create_activation_service()
    employees = await load_roster()
    return await active.issue_codes(tuple(str(employee.id) for employee in employees))


def _default_completion_source() -> NocoDBCompletionSource:
    try:
        return create_completion_source()
    except OperationConfigurationError:
        return create_local_completion_source()


async def completion_status(
    period: DateRange,
    employee: str | None = None,
    source: NocoDBCompletionSource | None = None,
) -> CompletionReport:
    active = source if source is not None else _default_completion_source()
    return evaluate_completion(period, await active.load(period, employee))


async def export_attendance(
    period: DateRange,
    employees: tuple[str, ...] = (),
    backend: PostgresWebBackend | None = None,
) -> tuple[str, int]:
    from digital_bast.web.csv_export import attendance_csv  # noqa: PLC0415

    active = backend if backend is not None else create_attendance_backend()
    rows: tuple[AttendanceRow, ...] = await active.attendance(employees, period.start, period.end)
    return attendance_csv(rows), len(rows)


async def export_attendance_report(
    period: DateRange,
    report_type: str,
    backend: PostgresWebBackend | None = None,
) -> tuple[Path, int]:
    active = backend if backend is not None else create_attendance_backend()
    role = _REPORT_TYPE_ROLE[report_type]
    content, rows = await active.attendance_legacy(role, period.start, period.end)
    suffix = _REPORT_TYPE_SUFFIX[report_type]
    filename = (
        f"Attendance_Celerates_Combined_{period.start.isoformat()}"
        f"_to_{period.end.isoformat()} ({suffix}).csv"
    )
    _EXPORTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = _EXPORTS_DIRECTORY / filename
    _ = path.write_text(content, encoding="utf-8", newline="")
    return path, rows


async def generate_status_matrix(period: DateRange) -> Path:
    # local: same rationale as generate_bast -- keep Playwright off the
    # bot-reply import path for commands that never render anything.
    from digital_bast.bot.whatsapp import render_status_matrix_html  # noqa: PLC0415
    from digital_bast.infrastructure.pdf_export import render_png  # noqa: PLC0415

    report = await completion_status(period)
    png_bytes = await render_png(render_status_matrix_html(report))
    _EXPORTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    filename = f"BAST_status_{period.start.isoformat()}_{period.end.isoformat()}.png"
    path = _EXPORTS_DIRECTORY / filename
    _ = path.write_bytes(png_bytes)
    return path


async def generate_bast(
    period: DateRange,
    report_type: str = "developer",
) -> tuple[Path, AssembledReport]:
    # local: digital_bast.web's package init pulls in the full FastAPI app,
    # redis, etc. -- keep that off commands that never touch the web app.
    from digital_bast.infrastructure.pdf_export import render_pdf  # noqa: PLC0415
    from digital_bast.web.bast_assembler import (  # noqa: PLC0415
        PostgresBastArtifactStore,
        assemble,
    )

    settings = _settings()
    dsn = settings.database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    secret = dsn.get_secret_value()
    report = await assemble(report_type, period.start.year, period.start.month, secret)
    pdf_bytes = await render_pdf(report.editor_html)
    _ = await PostgresBastArtifactStore(secret).save(report)
    _EXPORTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    filename = f"BAST_{report_type}_{report.year}-{report.month:02d}.pdf"
    path = _EXPORTS_DIRECTORY / filename
    _ = path.write_bytes(pdf_bytes)
    return path, report
