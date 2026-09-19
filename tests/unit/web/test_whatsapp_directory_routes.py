from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from digital_bast.infrastructure.whatsapp_directory import (
    PayrollClosingGroupSetting,
    TalentWhatsAppBindOutcome,
    TalentWhatsAppBindResult,
    TalentWhatsAppDirectoryRow,
)
from digital_bast.infrastructure.whatsapp_outbound import (
    WhatsAppGroup,
    WhatsAppGroupDirectory,
    WhatsAppGroupParticipant,
)
from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import CookieSettings
from digital_bast.web.whatsapp_directory_router import whatsapp_directory_router

_NOW = datetime(2026, 9, 19, 14, 0, tzinfo=UTC)
_CSRF = "synthetic-whatsapp-directory-csrf"


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


class _Bridge:
    def __init__(self, directory: WhatsAppGroupDirectory) -> None:
        self.directory = directory

    async def get_groups(self) -> WhatsAppGroupDirectory:
        return self.directory


class _Store:
    def __init__(self) -> None:
        self.talents = (
            TalentWhatsAppDirectoryRow(
                employee_id="EMP-1",
                nrp="10001",
                full_name="Andi",
                role="Developer",
                wa_jid="628111@c.us",
                bound_at=_NOW,
            ),
            TalentWhatsAppDirectoryRow(
                employee_id="EMP-2",
                nrp="10002",
                full_name="Budi",
                role="IoT Operations",
                wa_jid=None,
                bound_at=None,
            ),
        )
        self.bind_outcome = TalentWhatsAppBindOutcome.BOUND
        self.saved_groups: list[tuple[str, str | None, str]] = []
        self.setting = PayrollClosingGroupSetting("default", None)

    async def list_talents(self) -> tuple[TalentWhatsAppDirectoryRow, ...]:
        return self.talents

    async def bind(self, employee_id: str, wa_jid: str) -> TalentWhatsAppBindResult:
        return TalentWhatsAppBindResult(self.bind_outcome, employee_id, wa_jid)

    async def unbind(self, employee_id: str) -> bool:
        return employee_id == "EMP-1"

    async def closing_group(self, scope_key: str) -> PayrollClosingGroupSetting:
        return PayrollClosingGroupSetting(scope_key, self.setting.group_jid)

    async def save_closing_group(
        self,
        scope_key: str,
        group_jid: str | None,
        actor: str,
    ) -> PayrollClosingGroupSetting:
        self.saved_groups.append((scope_key, group_jid, actor))
        self.setting = PayrollClosingGroupSetting(scope_key, group_jid)
        return self.setting


def _group_directory(*, ready: bool = True) -> WhatsAppGroupDirectory:
    return WhatsAppGroupDirectory(
        ready=ready,
        connection="connected" if ready else "unavailable",
        discovered_at=_NOW if ready else None,
        groups=(
            WhatsAppGroup(
                jid="120363000000000000@g.us",
                subject="Payroll Closing",
                participants=(
                    WhatsAppGroupParticipant(jid="628111@c.us", is_admin=True),
                    WhatsAppGroupParticipant(jid="628222@lid"),
                ),
            ),
        )
        if ready
        else (),
    )


def _client(
    *,
    role: str = "owner",
    directory: WhatsAppGroupDirectory | None = None,
) -> tuple[TestClient, _Store]:
    record = SessionRecord(
        user=AuthenticatedUser(
            id="operator-1",
            email="owner@example.com",
            name="Owner",
            role=role,
        ),
        csrf_token=_CSRF,
        created_at=_NOW,
        expires_at=datetime(2026, 9, 20, 14, 0, tzinfo=UTC),
    )
    store = _Store()
    deps = WebDependencies(
        authenticator=_Authenticator(),
        sessions=_Sessions(record),
        backend=_Backend(),
        cookie=CookieSettings(secure=False),
        bot_bridge_status=_Bridge(directory or _group_directory()),  # type: ignore[arg-type]
        now=lambda: _NOW,
    )
    app = FastAPI()
    app.include_router(whatsapp_directory_router(deps, store=store))
    client = TestClient(app)
    client.cookies.set("digital_bast_session", "session-1")
    return client, store


def test_directory_joins_discovered_member_to_existing_talent_mapping() -> None:
    client, _ = _client()

    response = client.get("/api/talentops/v1/whatsapp-directory")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["groups"][0]["subject"] == "Payroll Closing"
    first_member = payload["groups"][0]["participants"][0]
    assert first_member["employee_id"] == "EMP-1"
    assert first_member["nrp"] == "10001"
    assert payload["talents"][0]["discovered_in_groups"] is True
    assert payload["talents"][1]["discovered_in_groups"] is False


def test_admin_mapping_requires_csrf_and_preserves_conflict_outcome() -> None:
    client, store = _client()
    store.bind_outcome = TalentWhatsAppBindOutcome.JID_ALREADY_BOUND
    body = {"wa_jid": "628222@lid"}

    no_csrf = client.put(
        "/api/talentops/v1/whatsapp-directory/mappings/EMP-2",
        json=body,
    )
    conflict = client.put(
        "/api/talentops/v1/whatsapp-directory/mappings/EMP-2",
        json=body,
        headers={"X-CSRF-Token": _CSRF},
    )

    assert no_csrf.status_code == 403
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "jid_already_bound"


def test_pmo_can_read_directory_but_cannot_mutate_mapping() -> None:
    client, _ = _client(role="pmo")

    readable = client.get("/api/talentops/v1/whatsapp-directory")
    mutation = client.delete(
        "/api/talentops/v1/whatsapp-directory/mappings/EMP-1",
        headers={"X-CSRF-Token": _CSRF},
    )

    assert readable.status_code == 200
    assert mutation.status_code == 403


def test_closing_group_must_exist_in_ready_discovery_snapshot() -> None:
    client, store = _client()

    response = client.put(
        "/api/talentops/v1/whatsapp-directory/closing-group",
        json={"group_jid": "120363999999999999@g.us"},
        headers={"X-CSRF-Token": _CSRF},
    )

    assert response.status_code == 409
    assert store.saved_groups == []


def test_closing_group_can_be_saved_while_bridge_is_temporarily_unavailable() -> None:
    client, store = _client(directory=_group_directory(ready=False))
    group_jid = "120363999999999999@g.us"

    response = client.put(
        "/api/talentops/v1/whatsapp-directory/closing-group",
        json={"group_jid": group_jid},
        headers={"X-CSRF-Token": _CSRF},
    )

    assert response.status_code == 200
    assert response.json()["verified"] is False
    assert response.json()["group_jid"] == group_jid
    assert store.saved_groups == [("default", group_jid, "owner@example.com")]
