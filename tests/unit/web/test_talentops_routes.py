from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from digital_bast.application.talentops import (
    CommandCenterSummary,
    CommandCenterView,
    DeliverySummary,
    PeriodView,
)
from digital_bast.web import (
    AttendanceRow,
    AuthenticatedUser,
    CookieSettings,
    EmployeeOption,
    GenerationPlanInput,
    GenerationResult,
    ReportView,
    SectionInput,
    SessionId,
    SessionRecord,
    StreamSectionInput,
    WebDependencies,
    create_app,
)


class Authenticator:
    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        return None

    async def ready(self) -> bool:
        return True


class Sessions:
    def __init__(self, record: SessionRecord | None) -> None:
        self.record = record

    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        self.record = record

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        return self.record if session_id == SessionId("session-1") else None

    async def delete(self, session_id: SessionId) -> None:
        self.record = None

    async def ready(self) -> bool:
        return True


class Backend:
    async def ready(self) -> bool:
        return True

    async def report(
        self,
        report_type: str,
        year: int,
        month: int,
        evidence_only: bool,
    ) -> ReportView:
        return ReportView("", ())

    async def employees(self) -> tuple[EmployeeOption, ...]:
        return ()

    async def attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]:
        return ()

    async def create_plan(self, request: GenerationPlanInput) -> GenerationResult:
        return GenerationResult(success=True, plan_id="plan")

    async def generate_section(self, request: SectionInput) -> GenerationResult:
        return GenerationResult(success=True, plan_id=request.plan_id)

    async def bulk_data(self, plan_id: str) -> GenerationResult:
        return GenerationResult(success=True, plan_id=plan_id)

    async def store_section(self, request: StreamSectionInput) -> int:
        return 1


class TalentOps:
    async def command_center(self, period: object) -> CommandCenterView:
        return CommandCenterView(
            period=PeriodView(2026, 8, "2026-08-01", "2026-08-31", "1-31 Agustus 2026"),
            summary=CommandCenterSummary(0, 0, 0, 0, 0),
            attention=(),
            readiness=(),
            teams=(),
            delivery=DeliverySummary(0, 0, 0, ()),
            sources=(),
        )


class TalentOpsAi:
    async def answer(self, question: str, view: CommandCenterView) -> str | None:
        return "Grounded answer"


def make_client(authenticated: bool) -> TestClient:
    now = datetime(2026, 8, 3, 8, tzinfo=UTC)
    record = (
        SessionRecord(
            AuthenticatedUser("u-1", "owner@example.com", "Owner", "owner"),
            "csrf-token",
            now,
            now + timedelta(minutes=30),
        )
        if authenticated
        else None
    )
    dependencies = WebDependencies(
        authenticator=Authenticator(),
        sessions=Sessions(record),
        backend=Backend(),
        cookie=CookieSettings(secure=True),
        talentops=TalentOps(),  # type: ignore[arg-type]
        talentops_ai=TalentOpsAi(),  # type: ignore[arg-type]
        now=lambda: now,
    )
    client = TestClient(create_app(dependencies), base_url="https://testserver")
    if authenticated:
        client.cookies.set("digital_bast_session", "session-1", domain="testserver.local")
    return client


def test_talentops_api_requires_session() -> None:
    response = make_client(authenticated=False).get("/api/talentops/v1/command-center")
    assert response.status_code == 401


def test_talentops_session_bootstrap_returns_csrf() -> None:
    response = make_client(authenticated=True).get("/api/talentops/v1/session")
    assert response.status_code == 200
    assert isinstance(response.json()["csrf_token"], str)
    assert response.json()["csrf_token"]
    assert response.json()["timezone"] == "Asia/Jakarta"


def test_talentops_command_center_validates_period_pair() -> None:
    response = make_client(authenticated=True).get(
        "/api/talentops/v1/command-center?year=2026"
    )
    assert response.status_code == 422


def test_talentops_ai_requires_csrf_and_accepts_valid_header() -> None:
    client = make_client(authenticated=True)
    missing = client.post(
        "/api/talentops/v1/ai/command-center",
        json={"year": 2026, "month": 8, "question": "Explain blockers"},
    )
    valid = client.post(
        "/api/talentops/v1/ai/command-center",
        headers={"X-CSRF-Token": "csrf-token"},
        json={"year": 2026, "month": 8, "question": "Explain blockers"},
    )

    assert missing.status_code == 403
    assert valid.status_code == 200
    assert valid.json() == {"status": "ok", "answer": "Grounded answer"}
