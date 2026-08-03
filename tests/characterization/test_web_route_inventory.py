from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from datetime import date


class TestAuthenticator:
    async def authenticate_owner(self, email: str, credential: str) -> AuthenticatedUser | None:
        return None

    async def ready(self) -> bool:
        return True


class TestSessions:
    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        return None

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        return None

    async def delete(self, session_id: SessionId) -> None:
        return None

    async def ready(self) -> bool:
        return True


class TestBackend:
    async def ready(self) -> bool:
        return True

    async def report(
        self, report_type: str, year: int, month: int, evidence_only: bool
    ) -> ReportView:
        return ReportView("Synthetic", ())

    async def employees(self) -> tuple[EmployeeOption, ...]:
        return ()

    async def attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]:
        return ()

    async def create_plan(self, request: GenerationPlanInput) -> GenerationResult:
        return GenerationResult(success=True, plan_id="synthetic-plan")

    async def generate_section(self, request: SectionInput) -> GenerationResult:
        return GenerationResult(success=True, plan_id="synthetic-plan")

    async def bulk_data(self, plan_id: str) -> GenerationResult:
        return GenerationResult(success=True, plan_id="synthetic-plan")

    async def store_section(self, request: StreamSectionInput) -> int:
        return 1


def test_v2_route_inventory_preserves_v1_method_path_pairs() -> None:
    given = Path(__file__).parents[1] / "fixtures" / "web_routes_v1.json"
    with given.open(encoding="utf-8") as fixture_file:
        inventory = json.load(fixture_file)
    expected = {tuple(route) for route in inventory["routes"]}
    retired = {tuple(route) for route in inventory["retired_routes"]}

    app = create_app(
        WebDependencies(TestAuthenticator(), TestSessions(), TestBackend(), CookieSettings())
    )
    routes = tuple(app.routes) + tuple(
        nested_route
        for included_route in app.routes
        for nested_route in getattr(getattr(included_route, "original_router", None), "routes", ())
    )
    when = {
        (method, route.path)
        for route in routes
        for method in getattr(route, "methods", ())
        if method not in {"HEAD", "OPTIONS"}
    }

    assert expected <= when
    assert retired.isdisjoint(when)
    assert {("GET", "/health/live"), ("GET", "/health/ready")} <= when
