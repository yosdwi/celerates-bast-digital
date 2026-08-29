from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from pydantic import ValidationError

from digital_bast.application.workflow_control import WorkflowControlService
from digital_bast.bot.attendance_evidence import AttendanceEvidenceService
from digital_bast.bot.attendance_resolution import AttendanceResolutionService
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDmStateService
from digital_bast.bot.evidence import EvidenceService
from digital_bast.bot.identity import ActivationService
from digital_bast.bot.llm import LlmInterpreter
from digital_bast.bot.pmo_state import PmoDmStateService
from digital_bast.bot.rebind import IdentityRebindService
from digital_bast.config import Settings, SettingsConfigurationError, get_settings
from digital_bast.domain.completion import CompletionReport, evaluate_completion
from digital_bast.infrastructure.completion_source import CompletionSource

if TYPE_CHECKING:
    from digital_bast.domain.completion import DateRange
    from digital_bast.domain.models import Employee
    from digital_bast.web.bast_assembler import AssembledReport
    from digital_bast.web.contracts import AttendanceRow
    from digital_bast.web.postgres_backend import PostgresWebBackend

_DEFAULT_EXPORTS_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2] / "bot-worker" / "data" / "exports"
)
_REPORT_TYPE_ROLE: Final = {"developer": "Developer", "shifting": "IoT Operations"}
_REPORT_TYPE_SUFFIX: Final = {"developer": "DEVELOPER", "shifting": "SHIFTING"}
_MISSING_APP_DSN: Final = "APP_DATABASE_DSN"
_INVALID_SETTINGS: Final = "application settings are invalid; check .env and the secret files"


def _settings() -> Settings:
    try:
        return get_settings()
    except (ValidationError, SettingsConfigurationError, OSError) as error:
        raise OperationConfigurationError(_INVALID_SETTINGS) from error


def _application_dsn() -> str:
    dsn = _settings().database_dsn
    if dsn is None:
        raise OperationConfigurationError(_MISSING_APP_DSN)
    return dsn.get_secret_value()


def _exports_directory() -> Path:
    configured = _settings().bast_exports_dir
    return configured if configured is not None else _DEFAULT_EXPORTS_DIRECTORY


class OperationConfigurationError(RuntimeError):
    def __init__(self, missing: str) -> None:
        super().__init__(missing)
        self.missing: str = missing

    @override
    def __str__(self) -> str:
        return f"missing configuration for this command: {self.missing}"


def create_completion_source() -> CompletionSource:
    """Completion facts from the single typed app-Postgres store."""
    from digital_bast.infrastructure.local_completion_source import (  # noqa: PLC0415
        PostgresAttendanceFactReader,
        PostgresTaskEvidenceReader,
    )
    from digital_bast.infrastructure.postgres_employees import (  # noqa: PLC0415
        PostgresEmployeeSource,
    )
    from digital_bast.infrastructure.repositories import PostgresDomainRepository  # noqa: PLC0415

    secret = _application_dsn()
    return CompletionSource(
        PostgresEmployeeSource(secret),
        PostgresDomainRepository(secret),
        PostgresAttendanceFactReader(secret),
        PostgresTaskEvidenceReader(secret),
    )


def create_attendance_backend() -> PostgresWebBackend:
    from digital_bast.web.postgres_backend import PostgresWebBackend  # noqa: PLC0415

    return PostgresWebBackend(_application_dsn())


def create_activation_service() -> ActivationService:
    return ActivationService(_application_dsn())


def create_evidence_service() -> EvidenceService:
    return EvidenceService(_application_dsn())


def create_attendance_evidence_service() -> AttendanceEvidenceService:
    return AttendanceEvidenceService(_application_dsn())


def create_attendance_resolution_service() -> AttendanceResolutionService:
    return AttendanceResolutionService(_application_dsn())


def create_attendance_resolution_dm_state_service() -> AttendanceResolutionDmStateService:
    return AttendanceResolutionDmStateService(_application_dsn())


def create_workflow_control_service() -> WorkflowControlService:
    return WorkflowControlService(_application_dsn())


def create_identity_rebind_service() -> IdentityRebindService:
    return IdentityRebindService(_application_dsn())


def create_pmo_dm_state_service() -> PmoDmStateService:
    return PmoDmStateService(_application_dsn())


def create_llm_interpreter() -> LlmInterpreter | None:
    settings = _settings()
    if settings.bot_llm_url is None:
        return None
    return LlmInterpreter(str(settings.bot_llm_url), settings.bot_llm_model)


async def load_roster() -> tuple[Employee, ...]:
    from digital_bast.infrastructure.postgres_employees import (  # noqa: PLC0415
        PostgresEmployeeSource,
    )

    return await PostgresEmployeeSource(_application_dsn()).load()


async def issue_activation_codes(service: ActivationService | None = None) -> dict[str, str]:
    active = service if service is not None else create_activation_service()
    employees = await load_roster()
    return await active.issue_codes(tuple(str(employee.id) for employee in employees))


async def completion_status(
    period: DateRange,
    employee: str | None = None,
    source: CompletionSource | None = None,
) -> CompletionReport:
    active = source if source is not None else create_completion_source()
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
    employee: str | None = None,
    backend: PostgresWebBackend | None = None,
) -> tuple[Path, int]:
    active = backend if backend is not None else create_attendance_backend()
    role = _REPORT_TYPE_ROLE[report_type]
    content, rows = await active.attendance_legacy(role, period.start, period.end, employee)
    suffix = _REPORT_TYPE_SUFFIX[report_type]
    filename = (
        f"Attendance_Celerates_Combined_{period.start.isoformat()}"
        f"_to_{period.end.isoformat()} ({suffix}).csv"
    )
    exports_directory = _exports_directory()
    exports_directory.mkdir(parents=True, exist_ok=True)
    path = exports_directory / filename
    _ = path.write_text(content, encoding="utf-8", newline="")
    return path, rows


async def generate_status_matrix(period: DateRange) -> Path:
    from digital_bast.bot.whatsapp import render_status_matrix_html  # noqa: PLC0415
    from digital_bast.infrastructure.pdf_export import render_png  # noqa: PLC0415

    report = await completion_status(period)
    png_bytes = await render_png(render_status_matrix_html(report))
    exports_directory = _exports_directory()
    exports_directory.mkdir(parents=True, exist_ok=True)
    filename = f"BAST_status_{period.start.isoformat()}_{period.end.isoformat()}.png"
    path = exports_directory / filename
    _ = path.write_bytes(png_bytes)
    return path


async def generate_bast(
    period: DateRange,
    report_type: str = "developer",
) -> tuple[Path, AssembledReport]:
    from digital_bast.infrastructure.pdf_export import render_pdf  # noqa: PLC0415
    from digital_bast.web.bast_assembler import (  # noqa: PLC0415
        PostgresBastArtifactStore,
        assemble,
    )

    secret = _application_dsn()
    report = await assemble(report_type, period.start.year, period.start.month, secret)
    pdf_bytes = await render_pdf(report.editor_html)
    _ = await PostgresBastArtifactStore(secret).save(report)
    exports_directory = _exports_directory()
    exports_directory.mkdir(parents=True, exist_ok=True)
    filename = f"BAST_{report_type}_{report.year}-{report.month:02d}.pdf"
    path = exports_directory / filename
    _ = path.write_bytes(pdf_bytes)
    return path, report
