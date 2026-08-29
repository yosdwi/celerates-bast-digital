from datetime import date

from pydantic import ValidationError
from redis.asyncio import Redis

from digital_bast.application.bast_workflow import BastWorkflowService
from digital_bast.application.talentops import TalentOpsService
from digital_bast.application.talentops_ai import TalentOpsAiService
from digital_bast.application.workflow_control import WorkflowControlService
from digital_bast.bot.attendance_resolution import AttendanceResolutionService
from digital_bast.bot.rebind import IdentityRebindService
from digital_bast.config import get_settings
from digital_bast.infrastructure.cloudflare_workers_ai_chat import (
    CloudflareWorkersAiChatClient,
)
from digital_bast.infrastructure.completion_source import CompletionSource
from digital_bast.infrastructure.groq_chat import GroqChatClient
from digital_bast.infrastructure.local_completion_source import (
    PostgresAttendanceFactReader,
    PostgresTaskEvidenceReader,
)
from digital_bast.infrastructure.ollama_chat import OllamaChatClient
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.redis_url import parse_redis_url
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.infrastructure.source_sync_state import PostgresSourceSyncStateStore
from digital_bast.infrastructure.whatsapp_outbound import BotBridgeWhatsAppOutboundGateway
from digital_bast.web.contracts import (
    AttendanceRow,
    AuthenticatedUser,
    EmployeeOption,
    GenerationPlanInput,
    GenerationResult,
    OwnerAuthenticator,
    ReportView,
    SectionInput,
    SessionId,
    SessionRecord,
    SessionStore,
    StreamSectionInput,
    WebBackend,
)
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.errors import (
    AuthenticationUnavailableError,
    SessionUnavailableError,
    WebBackendUnavailableError,
)
from digital_bast.web.nocodb_postgres_auth import NocoDBPostgresOwnerAuthenticator
from digital_bast.web.postgres_backend import PostgresWebBackend
from digital_bast.web.security import CookieSettings
from digital_bast.web.sessions import RedisSessionStore


class UnavailableAuthenticator:
    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        _ = (email, password)
        raise AuthenticationUnavailableError

    async def ready(self) -> bool:
        return False


class UnavailableSessionStore:
    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        _ = (session_id, record, ttl_seconds)
        raise SessionUnavailableError(operation="create")

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        _ = session_id
        raise SessionUnavailableError(operation="read")

    async def delete(self, session_id: SessionId) -> None:
        _ = session_id
        raise SessionUnavailableError(operation="delete")

    async def ready(self) -> bool:
        return False


class UnavailableWebBackend:
    async def ready(self) -> bool:
        return False

    async def report(
        self, report_type: str, year: int, month: int, evidence_only: bool
    ) -> ReportView:
        _ = (report_type, year, month, evidence_only)
        raise WebBackendUnavailableError(operation="report")

    async def employees(self) -> tuple[EmployeeOption, ...]:
        raise WebBackendUnavailableError(operation="employees")

    async def attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]:
        _ = (employee_names, start_date, end_date)
        raise WebBackendUnavailableError(operation="attendance")

    async def create_plan(self, request: GenerationPlanInput) -> GenerationResult:
        _ = request
        raise WebBackendUnavailableError(operation="create_plan")

    async def generate_section(self, request: SectionInput) -> GenerationResult:
        _ = request
        raise WebBackendUnavailableError(operation="generate_section")

    async def bulk_data(self, plan_id: str) -> GenerationResult:
        _ = plan_id
        raise WebBackendUnavailableError(operation="bulk_data")

    async def store_section(self, request: StreamSectionInput) -> int:
        _ = request
        raise WebBackendUnavailableError(operation="store_section")


def production_dependencies() -> WebDependencies:
    try:
        settings = get_settings()
    except (OSError, ValidationError):
        return _unavailable_dependencies()

    app_dsn = settings.database_dsn.get_secret_value() if settings.database_dsn is not None else None

    sessions: SessionStore = UnavailableSessionStore()
    if settings.redis_url is not None:
        endpoint = parse_redis_url(settings.redis_url.get_secret_value())
        redis_client = Redis(
            host=endpoint.host,
            port=endpoint.port,
            db=endpoint.database,
            username=endpoint.username,
            password=endpoint.password,
            ssl=endpoint.ssl,
            socket_connect_timeout=5.0,
            socket_timeout=5.0,
            health_check_interval=30,
            decode_responses=True,
        )
        sessions = RedisSessionStore(redis_client)

    # Credentials stay in NocoDB. NocoDB owners are admins; other NocoDB users
    # can sign in only when an admin provisions them in workflow_operators.
    authenticator: OwnerAuthenticator = UnavailableAuthenticator()
    if settings.nocodb_database_dsn is not None and settings.nocodb_base_id is not None:
        authenticator = NocoDBPostgresOwnerAuthenticator(
            settings.nocodb_database_dsn.get_secret_value(),
            settings.nocodb_base_id,
            app_dsn=app_dsn,
        )

    bot_bridge_status: BotBridgeWhatsAppOutboundGateway | None = None
    if settings.bot_bridge_base_url is not None and settings.sync_ingest_token is not None:
        bot_bridge_status = BotBridgeWhatsAppOutboundGateway(
            str(settings.bot_bridge_base_url),
            settings.sync_ingest_token.get_secret_value(),
        )

    backend: WebBackend = UnavailableWebBackend()
    talentops: TalentOpsService | None = None
    talentops_ai: TalentOpsAiService | None = None
    attendance_resolutions: AttendanceResolutionService | None = None
    workflow_control: WorkflowControlService | None = None
    identity_rebinds: IdentityRebindService | None = None
    bast_workflow: BastWorkflowService | None = None
    source_sync_state: PostgresSourceSyncStateStore | None = None

    if app_dsn is not None:
        backend = PostgresWebBackend(app_dsn)
        employees = PostgresEmployeeSource(app_dsn)
        records = PostgresDomainRepository(app_dsn)
        completion = CompletionSource(
            employees,
            records,
            PostgresAttendanceFactReader(app_dsn),
            PostgresTaskEvidenceReader(app_dsn),
        )
        source_sync_state = PostgresSourceSyncStateStore(app_dsn)
        attendance_resolutions = AttendanceResolutionService(app_dsn)
        workflow_control = WorkflowControlService(app_dsn)
        identity_rebinds = IdentityRebindService(app_dsn)
        talentops = TalentOpsService(
            completion,
            employees,
            records,
            source_sync_state,
        )
        bast_workflow = BastWorkflowService(app_dsn, talentops)

        if (
            settings.llm_provider == "cloudflare"
            and settings.cloudflare_account_id is not None
            and settings.cloudflare_api_token is not None
        ):
            talentops_ai = TalentOpsAiService(
                CloudflareWorkersAiChatClient(
                    settings.cloudflare_account_id,
                    settings.cloudflare_api_token.get_secret_value(),
                    settings.cloudflare_workers_ai_model,
                )
            )
        elif settings.llm_provider == "groq" and settings.groq_api_key is not None:
            talentops_ai = TalentOpsAiService(
                GroqChatClient(
                    settings.groq_api_key.get_secret_value(),
                    settings.groq_model,
                )
            )
        elif settings.llm_provider == "ollama" and settings.bot_llm_url is not None:
            talentops_ai = TalentOpsAiService(
                OllamaChatClient(
                    str(settings.bot_llm_url),
                    settings.bot_llm_model,
                )
            )

    return WebDependencies(
        authenticator=authenticator,
        sessions=sessions,
        backend=backend,
        cookie=CookieSettings(ttl_seconds=settings.session_ttl_seconds),
        talentops=talentops,
        talentops_ai=talentops_ai,
        attendance_resolutions=attendance_resolutions,
        workflow_control=workflow_control,
        identity_rebinds=identity_rebinds,
        bast_workflow=bast_workflow,
        source_sync_state=source_sync_state,
        bot_bridge_status=bot_bridge_status,
    )


def _unavailable_dependencies() -> WebDependencies:
    return WebDependencies(
        authenticator=UnavailableAuthenticator(),
        sessions=UnavailableSessionStore(),
        backend=UnavailableWebBackend(),
        cookie=CookieSettings(),
    )
