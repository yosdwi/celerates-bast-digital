from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from digital_bast.web import (
    AttendanceRow,
    AuthenticatedUser,
    AuthenticationUnavailableError,
    CookieSettings,
    EmployeeOption,
    GenerationPlanInput,
    GenerationResult,
    ReportItem,
    ReportView,
    SectionInput,
    SessionId,
    SessionRecord,
    StreamSectionInput,
    WebDependencies,
    create_app,
)
from digital_bast.web.csv_export import neutralize_csv_formula

VALID_LOGIN_CREDENTIAL = "correct-credential"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 3, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


class FakeAuthenticator:
    def __init__(self) -> None:
        self.outage = False

    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        if self.outage:
            raise AuthenticationUnavailableError
        if email != "owner@example.com" or password != VALID_LOGIN_CREDENTIAL:
            return None
        return AuthenticatedUser("u-1", email, "Owner <script>alert(1)</script>", "owner")

    async def ready(self) -> bool:
        return not self.outage


class FakeSessions:
    def __init__(self) -> None:
        self.records: dict[SessionId, SessionRecord] = {}

    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        self.records[session_id] = record

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        return self.records.get(session_id)

    async def delete(self, session_id: SessionId) -> None:
        self.records.pop(session_id, None)

    async def ready(self) -> bool:
        return True


class FakeBackend:
    async def ready(self) -> bool:
        return True

    async def report(
        self, report_type: str, year: int, month: int, evidence_only: bool
    ) -> ReportView:
        return ReportView("Evidence", (ReportItem("Activity", "<img src=x onerror=alert(1)>"),))

    async def employees(self) -> tuple[EmployeeOption, ...]:
        return (EmployeeOption("Alice", "Developer"),)

    async def attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]:
        return (
            AttendanceRow(
                "=CMD()",
                "Alice",
                start_date,
                "N",
                "07:30",
                "16:30",
                "H",
                "07:31",
                "16:29",
                "+SUM(1,1)",
            ),
        )

    async def create_plan(self, request: GenerationPlanInput) -> GenerationResult:
        return GenerationResult(success=True, plan_id="plan-1")

    async def generate_section(self, request: SectionInput) -> GenerationResult:
        return GenerationResult(
            success=True,
            plan_id=request.plan_id,
            section_id=request.section_id,
            title="Section",
            content="safe",
        )

    async def bulk_data(self, plan_id: str) -> GenerationResult:
        return GenerationResult(
            success=True,
            plan_id=plan_id,
            title="Report",
            content="<script>bad()</script>",
        )

    async def store_section(self, request: StreamSectionInput) -> int:
        return 1


def make_client() -> tuple[TestClient, Clock, FakeSessions, FakeAuthenticator]:
    clock = Clock()
    sessions = FakeSessions()
    authenticator = FakeAuthenticator()
    dependencies = WebDependencies(
        authenticator=authenticator,
        sessions=sessions,
        backend=FakeBackend(),
        cookie=CookieSettings(secure=True, ttl_seconds=300),
        now=clock,
        session_id=lambda: "new-opaque-session",
    )
    client = TestClient(create_app(dependencies), base_url="https://testserver")
    return client, clock, sessions, authenticator


def login(client: TestClient) -> str:
    response = client.post(
        "/admin/auth/login",
        data={"email": "owner@example.com", "password": "correct-credential"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return next(iter(response.cookies.values()))


def test_health_and_readiness_are_public() -> None:
    client, _, _, _ = make_client()

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "components": {
            "session": "ready",
            "authentication": "ready",
            "backend": "ready",
        },
    }


def test_readiness_identifies_authentication_outage() -> None:
    client, _, _, authenticator = make_client()
    authenticator.outage = True

    ready = client.get("/health/ready")

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "components": {
            "session": "ready",
            "authentication": "not_ready",
            "backend": "ready",
        },
    }


def test_login_rotates_fixed_session_and_sets_secure_cookie() -> None:
    client, clock, sessions, _ = make_client()
    fixed = SessionId("attacker-fixed")
    sessions.records[fixed] = SessionRecord(
        AuthenticatedUser("old", "old@example.com", "Old", "owner"),
        "old-csrf",
        clock.value,
        clock.value + timedelta(minutes=5),
    )
    client.cookies.set("digital_bast_session", fixed, domain="testserver.local")

    response = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "correct-credential"},
        follow_redirects=False,
    )

    cookie = response.headers["set-cookie"]
    assert response.status_code == 303
    assert "attacker-fixed" not in sessions.records
    assert "new-opaque-session" in sessions.records
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie


def test_protected_routes_and_csrf_fail_closed() -> None:
    # "/admin/" itself is now a public, unconditional redirect to TalentOps
    # (still 303 either way, but no longer because of require_session) --
    # "/admin/legacy-reports" is the route that's actually gated.
    client, _, _, _ = make_client()

    page = client.get("/admin/legacy-reports", follow_redirects=False)
    api = client.post("/api/generate/plan", data={"type": "developer", "month": 8})
    login(client)
    missing = client.post("/api/generate/plan", data={"type": "developer", "month": 8})
    invalid = client.post(
        "/api/generate/plan",
        data={"type": "developer", "month": 8, "_csrf_token": "wrong"},
    )

    assert page.status_code == 303
    assert api.status_code == 401
    assert missing.status_code == 403
    assert invalid.status_code == 403


def test_session_expiry_removes_server_record() -> None:
    # "/admin/" is now an unconditional redirect straight to TalentOps (it
    # never touches the session store itself) -- "/admin/legacy-reports"
    # still runs through require_session()/load_session() the same way
    # "/admin/" used to, so it's the one that still exercises expiry cleanup.
    client, clock, sessions, _ = make_client()
    login(client)
    clock.value += timedelta(minutes=6)

    response = client.get("/admin/legacy-reports", follow_redirects=False)

    assert response.status_code == 303
    assert not sessions.records


def test_templates_escape_untrusted_html() -> None:
    # "/admin/" no longer renders dashboard.html itself -- it redirects to
    # TalentOps. "/admin/legacy-reports" is the Jinja2-templated page this
    # test actually needs to check for escaping.
    client, _, sessions, _ = make_client()
    login(client)
    csrf = next(iter(sessions.records.values())).csrf_token

    dashboard = client.get("/admin/legacy-reports")
    report = client.post(
        "/report/evidence",
        data={"type": "developer", "month": 8, "_csrf_token": csrf},
    )

    assert "<script>alert(1)</script>" not in dashboard.text
    assert "<img src=x" not in report.text
    assert "&lt;img src=x" in report.text


def test_csv_export_neutralizes_formulas() -> None:
    client, _, sessions, _ = make_client()
    login(client)
    csrf = next(iter(sessions.records.values())).csrf_token

    response = client.post(
        "/admin/attendance-celerates/export-csv",
        data={
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "export_mode": "combined",
            "_csrf_token": csrf,
        },
    )

    assert response.status_code == 200
    assert "'=CMD()" in response.text
    assert "'+SUM(1,1)" in response.text
    assert neutralize_csv_formula(" safe") == " safe"


def test_authentication_outage_is_safe() -> None:
    client, _, _, authenticator = make_client()
    authenticator.outage = True

    response = client.post("/auth/login", data={"email": "owner@example.com", "password": "secret"})

    assert response.status_code == 503
    assert "temporarily unavailable" in response.text
    assert "secret" not in response.text
