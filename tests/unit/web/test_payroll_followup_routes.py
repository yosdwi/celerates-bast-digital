from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_closing_settings import PayrollClosingSettings
from digital_bast.application.payroll_digest import (
    PayrollClosingDigest,
    PayrollDigestSummary,
    PayrollFollowUpItem,
    PayrollFollowUpReason,
)
from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState
from digital_bast.application.payroll_reminders import (
    PayrollManualReminderPreview,
    PayrollManualReminderResult,
)
from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.payroll_followup_router import payroll_followup_router
from digital_bast.web.security import CookieSettings

_NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
_CYCLE = payroll_cycle(2026, 9)
_CSRF = uuid4().hex


class _Authenticator:
    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        _ = (email, password)
        return None

    async def ready(self) -> bool:
        return True


class _Sessions:
    def __init__(self, record: SessionRecord) -> None:
        self.record = record

    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        _ = (session_id, ttl_seconds)
        self.record = record

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        return self.record if session_id == SessionId("session-1") else None

    async def delete(self, session_id: SessionId) -> None:
        _ = session_id

    async def ready(self) -> bool:
        return True


class _Backend:
    async def ready(self) -> bool:
        return True


class _Settings:
    async def load(self, scope_key: str = "default") -> PayrollClosingSettings:
        assert scope_key == "default"
        return PayrollClosingSettings(enabled=True, next_day_ready_hour=7)

    async def save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings:
        return settings

    async def mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings:
        _ = (scope_key, version)
        return PayrollClosingSettings(enabled=True, applied_version=1)


class _Digest:
    async def project(
        self,
        cycle: object,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
        target_roles: tuple[str, ...] | None = None,
    ) -> PayrollClosingDigest:
        assert cycle == _CYCLE
        assert now == _NOW
        assert next_day_ready_hour == 7
        assert target_roles == ("Developer", "IoT Operations")
        return PayrollClosingDigest(
            cycle=_CYCLE,
            evaluated_through=date(2026, 9, 18),
            summary=PayrollDigestSummary(
                total_talents=2,
                complete=0,
                waiting_submitted=1,
                needs_talent_action=1,
                unverified=0,
                successful_reminder_deliveries=1,
                successfully_reminded_talents=1,
                unresponded_talents=1,
                actionable_not_reminded=0,
                delivery_retryable_failed=0,
                delivery_final_failed=0,
                delivery_unknown=0,
            ),
            items=(
                PayrollFollowUpItem(
                    employee_id="emp-a",
                    nrp="A01",
                    name="Andi",
                    role="Developer",
                    status="NEEDS_TALENT_ACTION",
                    actionable_days=1,
                    waiting_days=0,
                    unverified_days=0,
                    reason=PayrollFollowUpReason.UNRESPONDED,
                    latest_delivery_state=PayrollDeliveryState.SENT,
                    latest_milestone="H-1",
                ),
            ),
        )


class _Reminders:
    def __init__(self) -> None:
        self.sent: list[tuple[str, UUID]] = []

    async def preview_manual(
        self,
        employee_id: str,
        cycle: object,
        *,
        now: datetime,
    ) -> PayrollManualReminderPreview:
        assert cycle == _CYCLE
        assert now == _NOW
        return PayrollManualReminderPreview(
            employee_id=employee_id,
            eligible=True,
            outcome="ready",
            actionable_days=1,
            message="Halo Andi, ada attendance yang perlu dilengkapi.",
        )

    async def send_manual(
        self,
        employee_id: str,
        cycle: object,
        request_id: UUID,
        *,
        now: datetime,
    ) -> PayrollManualReminderResult:
        assert cycle == _CYCLE
        assert now == _NOW
        self.sent.append((employee_id, request_id))
        return PayrollManualReminderResult(
            employee_id=employee_id,
            outcome="sent",
            sent=True,
        )


def _client() -> tuple[TestClient, _Reminders]:
    record = SessionRecord(
        user=AuthenticatedUser(
            id="owner-1",
            email="owner@example.com",
            name="Owner",
            role="owner",
        ),
        csrf_token=_CSRF,
        created_at=_NOW,
        expires_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
    )
    deps = WebDependencies(
        authenticator=_Authenticator(),
        sessions=_Sessions(record),
        backend=_Backend(),
        cookie=CookieSettings(secure=False),
        now=lambda: _NOW,
    )
    reminders = _Reminders()
    app = FastAPI()
    app.include_router(
        payroll_followup_router(
            deps,
            digest_service=_Digest(),
            reminder_service=reminders,
            settings_store=_Settings(),
        )
    )
    client = TestClient(app)
    client.cookies.set("digital_bast_session", "session-1")
    return client, reminders


def test_payroll_digest_exposes_correlated_follow_up_facts() -> None:
    client, _ = _client()

    response = client.get("/api/talentops/v1/payroll/digest?year=2026&month=9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cycle"]["cycle_id"] == _CYCLE.cycle_id
    assert payload["summary"]["unresponded_talents"] == 1
    assert payload["summary"]["successful_reminder_deliveries"] == 1
    assert payload["items"][0]["reason"] == "UNRESPONDED"
    assert payload["items"][0]["latest_delivery_state"] == "SENT"


def test_payroll_follow_up_preview_uses_current_cycle() -> None:
    client, _ = _client()

    response = client.get(
        "/api/talentops/v1/payroll/follow-up/emp-a/preview?year=2026&month=9"
    )

    assert response.status_code == 200
    assert response.json()["eligible"] is True
    assert "Andi" in response.json()["message"]


def test_payroll_manual_send_requires_csrf_and_preserves_request_id() -> None:
    client, reminders = _client()
    request_id = uuid4()
    path = "/api/talentops/v1/payroll/follow-up/emp-a/send?year=2026&month=9"

    rejected = client.post(path, json={"request_id": str(request_id)})
    accepted = client.post(
        path,
        headers={"X-CSRF-Token": _CSRF},
        json={"request_id": str(request_id)},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {
        "employee_id": "emp-a",
        "outcome": "sent",
        "sent": True,
    }
    assert reminders.sent == [("emp-a", request_id)]
