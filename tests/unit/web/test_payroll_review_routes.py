from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.attendance_review import AttendanceReviewEvidenceMetadata
from digital_bast.application.payroll_read import (
    PayrollDayView,
    PayrollOverview,
    PayrollSummary,
    PayrollTalentView,
)
from digital_bast.bot.attendance_resolution import (
    AttendanceResolution,
    DecisionOutcome,
    DecisionResult,
    ResolutionStatus,
    ResolutionType,
)
from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.payroll_router import payroll_router
from digital_bast.web.security import CookieSettings

_REQUEST_ID = UUID("00000000-0000-0000-0000-000000000401")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000402")
_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_CYCLE = payroll_cycle(2026, 9)
_CSRF_TOKEN = "csrf-payroll-review-test-token"  # noqa: S105 - synthetic test value


class _Authenticator:
    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        return None

    async def ready(self) -> bool:
        return True


class _Sessions:
    def __init__(self, record: SessionRecord) -> None:
        self.record = record

    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        self.record = record

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        return self.record if session_id == SessionId("session-1") else None

    async def delete(self, session_id: SessionId) -> None:
        return None

    async def ready(self) -> bool:
        return True


class _Backend:
    async def ready(self) -> bool:
        return True


class _Payroll:
    async def overview(self, cycle: object, *, now: datetime) -> PayrollOverview:
        assert cycle == _CYCLE
        day = PayrollDayView(
            attendance_id=44,
            attendance_key="ATT-44",
            work_date=date(2026, 9, 4),
            schedule_state=AttendanceScheduleState.WORKING,
            source_state=AttendanceSourceState.AVAILABLE,
            raw_check_in="07:30",
            raw_check_out=None,
            proposed_check_in=None,
            proposed_check_out="17:40",
            resolution_id=str(_REQUEST_ID),
            resolution_status="pending",
            resolution_type="missing_clock_out",
            absence_type=None,
            rejection_reason=None,
            has_evidence=True,
            status=AttendanceClosingStatus.WAITING_SUBMITTED,
            reason=AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST,
            talent_action_required=False,
        )
        talent = PayrollTalentView(
            employee_id="EMP-1",
            nrp="10001",
            name="Andi",
            role="Developer",
            status=AttendanceClosingStatus.WAITING_SUBMITTED,
            evaluated_days=1,
            complete_days=0,
            waiting_days=1,
            actionable_days=0,
            unverified_days=0,
            days=(day,),
        )
        return PayrollOverview(
            cycle=_CYCLE,
            evaluated_through=date(2026, 9, 18),
            summary=PayrollSummary(1, 0, 1, 0, 0),
            talents=(talent,),
        )


class _Evidence:
    async def metadata(self, request_id: UUID) -> AttendanceReviewEvidenceMetadata:
        assert request_id == _REQUEST_ID
        return AttendanceReviewEvidenceMetadata(
            request_id=request_id,
            evidence_id=_EVIDENCE_ID,
            content_type="application/pdf",
            byte_size=2048,
            caption="surat",
            uploaded_at=_NOW,
        )


class _Resolutions:
    def __init__(self) -> None:
        self.decisions: list[tuple[UUID, bool, str | None]] = []

    async def pending(self) -> tuple[AttendanceResolution, ...]:
        return (
            AttendanceResolution(
                id=_REQUEST_ID,
                attendance_id=44,
                employee_id="EMP-1",
                nrp="10001",
                full_name="Andi",
                work_date=date(2026, 9, 4),
                resolution_type=ResolutionType.MISSING_CLOCK_OUT,
                absence_type=None,
                proposed_check_in=None,
                proposed_check_out=time(17, 40),
                status=ResolutionStatus.PENDING,
                evidence_id=_EVIDENCE_ID,
                requested_by_jid="628123@s.whatsapp.net",
                submitted_at=_NOW,
                reviewed_by=None,
                reviewed_at=None,
                rejection_reason=None,
            ),
        )

    async def decide(
        self,
        request_id: UUID,
        reviewer: str,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> DecisionResult:
        assert reviewer == "owner@example.com"
        self.decisions.append((request_id, approve, rejection_reason))
        return DecisionResult(
            DecisionOutcome.UPDATED,
            ResolutionStatus.APPROVED if approve else ResolutionStatus.REJECTED,
        )


class _AttendanceReview:
    async def metadata(self, request_id: UUID) -> AttendanceReviewEvidenceMetadata:
        return await _Evidence().metadata(request_id)


def _client() -> tuple[TestClient, _Resolutions]:
    record = SessionRecord(
        user=AuthenticatedUser(
            id="owner-1",
            email="owner@example.com",
            name="Owner",
            role="owner",
        ),
        csrf_token=_CSRF_TOKEN,
        created_at=_NOW,
        expires_at=datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
    )
    resolutions = _Resolutions()
    deps = WebDependencies(
        authenticator=_Authenticator(),
        sessions=_Sessions(record),
        backend=_Backend(),
        cookie=CookieSettings(secure=False),
        payroll_read=_Payroll(),
        attendance_resolutions=resolutions,
        attendance_review=_AttendanceReview(),
        now=lambda: _NOW,
    )
    app = FastAPI()
    app.include_router(payroll_router(deps))
    client = TestClient(app)
    client.cookies.set("digital_bast_session", "session-1")
    return client, resolutions


def test_review_queue_exposes_current_request_and_evidence_metadata() -> None:
    client, _ = _client()

    response = client.get("/api/talentops/v1/payroll/review-queue?year=2026&month=9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["reviewable"] == 1
    assert payload["summary"]["missing_clock_out"] == 1
    item = payload["items"][0]
    assert item["request_id"] == str(_REQUEST_ID)
    assert item["raw_check_in"] == "07:30"
    assert item["proposed_check_out"] == "17:40"
    assert item["evidence_content_type"] == "application/pdf"
    assert item["evidence_byte_size"] == 2048
    assert item["reviewable"] is True


def test_bulk_decision_requires_csrf_and_returns_item_result() -> None:
    client, resolutions = _client()
    body = {"request_ids": [str(_REQUEST_ID)], "decision": "approve"}

    forbidden = client.post(
        "/api/talentops/v1/payroll/review-queue/decide?year=2026&month=9",
        json=body,
    )
    approved = client.post(
        "/api/talentops/v1/payroll/review-queue/decide?year=2026&month=9",
        json=body,
        headers={"X-CSRF-Token": _CSRF_TOKEN},
    )

    assert forbidden.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["succeeded"] == 1
    assert approved.json()["items"][0]["outcome"] == "approved"
    assert resolutions.decisions == [(_REQUEST_ID, True, None)]


def test_reject_without_reason_is_rejected_before_mutation() -> None:
    client, resolutions = _client()

    response = client.post(
        "/api/talentops/v1/payroll/review-queue/decide?year=2026&month=9",
        json={"request_ids": [str(_REQUEST_ID)], "decision": "reject"},
        headers={"X-CSRF-Token": _CSRF_TOKEN},
    )

    assert response.status_code == 422
    assert "rejection_reason" in response.json()["detail"]
    assert resolutions.decisions == []
