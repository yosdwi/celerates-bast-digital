from datetime import date
from typing import ClassVar, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis

from digital_bast.config import get_settings
from digital_bast.infrastructure.redis_url import parse_redis_url
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
)
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.errors import (
    AuthenticationUnavailableError,
    SessionUnavailableError,
    WebBackendUnavailableError,
)
from digital_bast.web.postgres_backend import PostgresWebBackend
from digital_bast.web.security import CookieSettings
from digital_bast.web.sessions import RedisSessionStore

_SERVER_ERROR_STATUS: Final = 500


class OfficialNocoDBOwnerAuthenticator:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client: httpx.AsyncClient = client

    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        try:
            response = await self._client.post(
                "/api/v1/auth/user/signin", json={"email": email, "password": password}
            )
            if response.status_code in {401, 403}:
                return None
            _ = response.raise_for_status()
            token = _TokenResponse.model_validate(response.json()).token
            me_response = await self._client.get("/api/v1/auth/user/me", headers={"xc-auth": token})
            if me_response.status_code in {401, 403}:
                return None
            _ = me_response.raise_for_status()
            user = _UserResponse.model_validate(me_response.json())
        except (httpx.HTTPError, ValidationError) as error:
            raise AuthenticationUnavailableError from error
        raw_roles = user.roles.split(",") if isinstance(user.roles, str) else user.roles
        roles = tuple(role.strip().casefold() for role in raw_roles)
        if "owner" not in roles:
            return None
        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            name=user.email.partition("@")[0],
            role="owner",
        )

    async def ready(self) -> bool:
        try:
            response = await self._client.get("/api/v1/health")
        except httpx.HTTPError:
            return False
        return response.status_code < _SERVER_ERROR_STATUS


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
    authenticator: OwnerAuthenticator = UnavailableAuthenticator()
    if settings.nocodb_base_url is not None:
        timeout = httpx.Timeout(
            connect=min(settings.outbound_timeout_seconds, 5.0),
            read=settings.outbound_timeout_seconds,
            write=min(settings.outbound_timeout_seconds, 10.0),
            pool=min(settings.outbound_timeout_seconds, 10.0),
        )
        client = httpx.AsyncClient(
            base_url=str(settings.nocodb_base_url),
            timeout=timeout,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={"Accept": "application/json"},
        )
        authenticator = OfficialNocoDBOwnerAuthenticator(client)
    backend = (
        PostgresWebBackend(settings.database_dsn.get_secret_value())
        if settings.database_dsn is not None
        else UnavailableWebBackend()
    )
    return WebDependencies(
        authenticator=authenticator,
        sessions=sessions,
        backend=backend,
        cookie=CookieSettings(ttl_seconds=settings.session_ttl_seconds),
    )


def _unavailable_dependencies() -> WebDependencies:
    return WebDependencies(
        authenticator=UnavailableAuthenticator(),
        sessions=UnavailableSessionStore(),
        backend=UnavailableWebBackend(),
        cookie=CookieSettings(),
    )


class _TokenResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    token: str = Field(min_length=1)


class _UserResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    id: str
    email: str
    roles: str | list[str] = Field(default_factory=list)
