from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.payroll_read import (
    PayrollDayView,
    PayrollOverview,
    PayrollSummary,
    PayrollTalentView,
)
from digital_bast.web.contracts import (
    AuthenticatedUser,
    SessionId,
    SessionRecord,
)
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.payroll_router import payroll_router
from digital_bast.web.security import CookieSettings


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

    async def report(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("Payroll read API must not call the BAST report backend")


class PayrollRead:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def overview(self, cycle: object, *, now: datetime) -> PayrollOverview:
        selected = cycle
        self.calls.append((selected.label_year, selected.label_month))
        day = PayrollDayView(
            attendance_id=1,
            attendance_key="attendance:emp-a:2026-09-10",
            work_date=date(2026, 9, 10),
            schedule_state=AttendanceScheduleState.WORKING,
            source_state=AttendanceSourceState.AVAILABLE,
            raw_check_in="08:00",
            raw_check_out="17:00",
            proposed_check_in=None,
            proposed_check_out=None,
            resolution_id=None,
            resolution_status=None,
            resolution_type=None,
            absence_type=None,
            rejection_reason=None,
            has_evidence=False,
            status=AttendanceClosingStatus.COMPLETE,
            reason=AttendanceClosingReason.RAW_COMPLETE,
            talent_action_required=False,
        )
        talent = PayrollTalentView(
            employee_id="emp-a",
            nrp="A01",
            name="Andi",
            role="Developer",
            status=AttendanceClosingStatus.COMPLETE,
            evaluated_days=1,
            complete_days=1,
            waiting_days=0,
            actionable_days=0,
            unverified_days=0,
            days=(day,),
        )
        return PayrollOverview(
            cycle=selected,
            evaluated_through=date(2026, 9, 18),
            summary=PayrollSummary(1, 1, 0, 0, 0),
            talents=(talent,),
        )


def _client() -> tuple[TestClient, PayrollRead]:
    now = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    record = SessionRecord(
        user=AuthenticatedUser(
            id="owner-1",
            email="owner@example.com",
            name="Owner",
            role="owner",
        ),
        csrf_token="csrf",
        created_at=now,
        expires_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
    )
    payroll = PayrollRead()
    deps = WebDependencies(
        authenticator=Authenticator(),
        sessions=Sessions(record),
        backend=Backend(),
        cookie=CookieSettings(secure=False),
        payroll_read=payroll,
        now=lambda: now,
    )
    app = FastAPI()
    app.include_router(payroll_router(deps))
    client = TestClient(app)
    client.cookies.set("digital_bast_session", "session-1")
    return client, payroll


def test_payroll_cycles_use_current_21_to_20_cycle() -> None:
    client, payroll = _client()

    response = client.get("/api/talentops/v1/payroll/cycles")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_cycle_id"] == "2026-09:2026-08-21:2026-09-20"
    assert payload["cycles"][0] == {
        "cycle_id": "2026-09:2026-08-21:2026-09-20",
        "label": "Payroll September 2026",
        "year": 2026,
        "month": 9,
        "start": "2026-08-21",
        "end": "2026-09-20",
    }
    assert payroll.calls == []


def test_payroll_overview_is_independent_from_bast_report_backend() -> None:
    client, payroll = _client()

    response = client.get("/api/talentops/v1/payroll/overview?year=2026&month=9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cycle"]["start"] == "2026-08-21"
    assert payload["cycle"]["end"] == "2026-09-20"
    assert payload["evaluated_through"] == "2026-09-18"
    assert payload["summary"] == {
        "total_talents": 1,
        "complete": 1,
        "waiting_submitted": 0,
        "needs_talent_action": 0,
        "unverified": 0,
    }
    assert payload["talents"][0]["employee_id"] == "emp-a"
    assert payload["talents"][0]["status"] == "COMPLETE"
    assert payroll.calls == [(2026, 9)]


def test_payroll_talent_detail_exposes_day_projection() -> None:
    client, payroll = _client()

    response = client.get("/api/talentops/v1/payroll/talents/emp-a?year=2026&month=9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["employee_id"] == "emp-a"
    assert payload["days"][0]["attendance_id"] == 1
    assert payload["days"][0]["raw_check_in"] == "08:00"
    assert payload["days"][0]["reason"] == "RAW_COMPLETE"
    assert payroll.calls == [(2026, 9)]


def test_payroll_api_rejects_partial_cycle_selector_and_unknown_talent() -> None:
    client, payroll = _client()

    invalid = client.get("/api/talentops/v1/payroll/overview?year=2026")
    missing = client.get("/api/talentops/v1/payroll/talents/not-found?year=2026&month=9")

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert payroll.calls == [(2026, 9)]
