from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from digital_bast.application.talentops import (
    AttendanceDay,
    CommandCenterSummary,
    CommandCenterView,
    DeliverySummary,
    PeriodView,
    ReadinessChecks,
    TalentDataAvailability,
    TalentDetailView,
    TalentTask,
    TimesheetDay,
    CheckSummary,
)
from digital_bast.domain.completion import CheckState
from digital_bast.domain.models import EmployeeRole
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

    async def talent_detail(self, period: object, nrp: str) -> TalentDetailView | None:
        if nrp != "JIMT24002":
            return None
        checks = ReadinessChecks(
            attendance=CheckSummary(CheckState.INCOMPLETE, 1),
            timesheet=CheckSummary(CheckState.INCOMPLETE, 1),
            task=CheckSummary(CheckState.COMPLETE, 0),
            evidence=CheckSummary(CheckState.COMPLETE, 0),
        )
        return TalentDetailView(
            period=PeriodView(2026, 8, "2026-08-01", "2026-08-31", "1-31 Agustus 2026"),
            nrp="JIMT24002",
            name="Yoses Dwi Maheswara",
            role=EmployeeRole.DEVELOPER,
            overall_state=CheckState.INCOMPLETE,
            checks=checks,
            blockers=(),
            attendance_days=(
                AttendanceDay(
                    work_date=date(2026, 8, 1),
                    is_off=False,
                    has_record=False,
                    has_clock_in=False,
                    has_clock_out=False,
                    has_evidence=False,
                    state=CheckState.INCOMPLETE,
                ),
            ),
            timesheet_days=(
                TimesheetDay(
                    work_date=date(2026, 8, 1),
                    is_off=False,
                    has_record=False,
                    has_remarks=False,
                    blocked_by_attendance=True,
                    state=CheckState.INCOMPLETE,
                ),
            ),
            tasks=(
                TalentTask(
                    work_date=date(2026, 8, 1),
                    title="Task",
                    status="Closed",
                    evidence_count=1,
                    is_closed=True,
                    evidence_ready=True,
                ),
            ),
            availability=TalentDataAvailability(attendance=True, evidence=True),
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


def test_talentops_talent_detail_requires_session_and_returns_grounded_payload() -> None:
    unauthenticated = make_client(authenticated=False).get(
        "/api/talentops/v1/talents/JIMT24002?year=2026&month=8"
    )
    response = make_client(authenticated=True).get(
        "/api/talentops/v1/talents/JIMT24002?year=2026&month=8"
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json()["nrp"] == "JIMT24002"
    assert response.json()["attendance_days"][0]["state"] == "incomplete"
    assert response.json()["timesheet_days"][0]["blocked_by_attendance"] is True
    assert response.json()["tasks"][0]["evidence_ready"] is True


def test_talentops_talent_detail_returns_404_for_unknown_nrp() -> None:
    response = make_client(authenticated=True).get(
        "/api/talentops/v1/talents/UNKNOWN?year=2026&month=8"
    )
    assert response.status_code == 404


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
