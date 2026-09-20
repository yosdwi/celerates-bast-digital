from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from digital_bast.infrastructure.whatsapp_outbound import (
    BotBridgeControlResult,
    BotBridgeStatus,
)
from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import CookieSettings
from digital_bast.web.whatsapp_ops_router import whatsapp_ops_router

_NOW = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
_CSRF = "whatsapp-ops-csrf"


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


class _Gateway:
    def __init__(self, status: BotBridgeStatus) -> None:
        self.status = status
        self.controls: list[str] = []
        self.pair_calls = 0

    async def get_status(self) -> BotBridgeStatus:
        return self.status

    async def control_recovery(self, action: str) -> BotBridgeControlResult:
        self.controls.append(action)
        return BotBridgeControlResult(accepted=True, reason=f"{action}_accepted")

    async def start_pairing(self) -> BotBridgeControlResult:
        self.pair_calls += 1
        return BotBridgeControlResult(accepted=True, reason="pairing_started")


def _client(
    status: BotBridgeStatus,
    *,
    role: str = "owner",
) -> tuple[TestClient, _Gateway]:
    record = SessionRecord(
        user=AuthenticatedUser(
            id="user-1",
            email="owner@example.com",
            name="Owner",
            role=role,
        ),
        csrf_token=_CSRF,
        created_at=_NOW,
        expires_at=datetime(2026, 9, 21, 8, 0, tzinfo=UTC),
    )
    gateway = _Gateway(status)
    deps = WebDependencies(
        authenticator=_Authenticator(),
        sessions=_Sessions(record),
        backend=_Backend(),
        cookie=CookieSettings(secure=False),
        bot_bridge_status=gateway,  # type: ignore[arg-type]
        now=lambda: _NOW,
    )
    app = FastAPI()
    app.include_router(whatsapp_ops_router(deps))
    client = TestClient(app)
    client.cookies.set("digital_bast_session", "session-1")
    return client, gateway


def _status(**changes: object) -> BotBridgeStatus:
    values: dict[str, object] = {
        "connection": "connected",
        "alive": True,
        "ready": True,
        "me": "628111@c.us",
        "recovery_state": "connected",
        "owner_acquired": True,
        "storage_healthy": True,
        "receipt_store_healthy": True,
        "recovery_policy_version": 1,
        "applied_recovery_policy_version": 1,
    }
    values.update(changes)
    return BotBridgeStatus(**values)  # type: ignore[arg-type]


def test_operations_status_exposes_alive_ready_recovery_and_safety_facts() -> None:
    client, _ = _client(
        _status(
            ready=False,
            connection="disconnected",
            recovery_state="recovering",
            recovery_reason="transient_disconnect",
            recovery_attempts=1,
            recovery_max_attempts=3,
            receipt_unknown=2,
        )
    )

    response = client.get("/api/talentops/v1/system/whatsapp/operations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["alive"] is True
    assert payload["ready"] is False
    assert payload["connection"] == "disconnected"
    assert payload["recovery_state"] == "recovering"
    assert payload["recovery_reason"] == "transient_disconnect"
    assert payload["owner_acquired"] is True
    assert payload["storage_healthy"] is True
    assert payload["receipt_store_healthy"] is True
    assert payload["receipt_unknown"] == 2


def test_recovery_control_requires_csrf_and_preserves_explicit_action() -> None:
    client, gateway = _client(_status(ready=False, connection="disconnected"))
    path = "/api/talentops/v1/system/whatsapp/recovery/reconnect"

    rejected = client.post(path)
    accepted = client.post(path, headers={"X-CSRF-Token": _CSRF})

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"accepted": True, "reason": "reconnect_accepted"}
    assert gateway.controls == ["reconnect"]


def test_pairing_is_admin_only_and_only_when_operator_action_is_required() -> None:
    ordinary_client, ordinary_gateway = _client(_status())
    ordinary = ordinary_client.post(
        "/api/talentops/v1/system/whatsapp/pair",
        headers={"X-CSRF-Token": _CSRF},
    )

    assert ordinary.status_code == 200
    assert ordinary.json() == {"accepted": False, "reason": "pairing_not_required"}
    assert ordinary_gateway.pair_calls == 0

    required_client, required_gateway = _client(
        _status(
            ready=False,
            connection="pairing-required",
            operator_action_required=True,
            operator_reason="logged-out: LOGOUT",
        )
    )
    required = required_client.post(
        "/api/talentops/v1/system/whatsapp/pair",
        headers={"X-CSRF-Token": _CSRF},
    )

    assert required.status_code == 200
    assert required.json() == {"accepted": True, "reason": "pairing_started"}
    assert required_gateway.pair_calls == 1

    non_admin_client, non_admin_gateway = _client(
        _status(
            ready=False,
            connection="pairing-required",
            operator_action_required=True,
        ),
        role="pmo",
    )
    forbidden = non_admin_client.post(
        "/api/talentops/v1/system/whatsapp/pair",
        headers={"X-CSRF-Token": _CSRF},
    )

    assert forbidden.status_code == 403
    assert non_admin_gateway.pair_calls == 0
