from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from digital_bast.application.payroll_export import PayrollExportRecord, PayrollExportService
from digital_bast.web.contracts import AuthenticatedUser, SessionId, SessionRecord
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.payroll_export_router import payroll_export_router
from digital_bast.web.security import CookieSettings


class Authenticator:
    async def authenticate_owner(self, email: str, password: str) -> AuthenticatedUser | None:
        return None

    async def ready(self) -> bool:
        return True


class Sessions:
    def __init__(self, record: SessionRecord) -> None:
        self.record = record

    async def create(self, session_id: SessionId, record: SessionRecord, ttl_seconds: int) -> None:
        self.record = record

    async def get(self, session_id: SessionId) -> SessionRecord | None:
        return self.record if session_id == SessionId("session-1") else None

    async def delete(self, session_id: SessionId) -> None:
        _ = session_id

    async def ready(self) -> bool:
        return True


class Backend:
    async def ready(self) -> bool:
        return True


class History:
    def __init__(self) -> None:
        self.items: list[PayrollExportRecord] = []

    async def record(self, item: PayrollExportRecord) -> PayrollExportRecord:
        self.items.append(item)
        return item

    async def list(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 50,
    ) -> tuple[PayrollExportRecord, ...]:
        selected = [item for item in self.items if cycle_id is None or item.cycle_id == cycle_id]
        return tuple(reversed(selected[-limit:]))


def _client(tmp_path: Path) -> tuple[TestClient, list[tuple[object, str, str | None]]]:
    now = datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    record = SessionRecord(
        user=AuthenticatedUser(
            id="owner-1",
            email="owner@example.com",
            name="Owner",
            role="owner",
        ),
        csrf_token="csrf",
        created_at=now,
        expires_at=datetime(2026, 9, 21, 5, 0, tzinfo=UTC),
    )
    calls: list[tuple[object, str, str | None]] = []
    path = tmp_path / "Attendance_Celerates_Combined_2026-08-21_to_2026-09-20 (DEVELOPER).csv"

    async def exporter(period: object, report_type: str, employee: str | None) -> tuple[Path, int]:
        calls.append((period, report_type, employee))
        path.write_text("Name,Date\nAndi,2026-09-01\n", encoding="utf-8")
        return path, 1

    deps = WebDependencies(
        authenticator=Authenticator(),
        sessions=Sessions(record),
        backend=Backend(),
        cookie=CookieSettings(secure=False),
        now=lambda: now,
    )
    app = FastAPI()
    app.include_router(
        payroll_export_router(
            deps,
            PayrollExportService(exporter, History(), now=lambda: now),
        )
    )
    client = TestClient(app)
    client.cookies.set("digital_bast_session", "session-1")
    return client, calls


def test_payroll_export_api_downloads_selected_cycle_and_records_history(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)

    response = client.post(
        "/api/talentops/v1/payroll/exports?year=2026&month=9",
        json={"report_type": "developer"},
        headers={"X-CSRF-Token": "csrf"},
    )

    assert response.status_code == 200
    assert response.text == "Name,Date\nAndi,2026-09-01\n"
    assert "Attendance_Celerates_Combined_2026-08-21_to_2026-09-20" in response.headers[
        "content-disposition"
    ]
    assert response.headers["x-payroll-cycle-id"] == "2026-09:2026-08-21:2026-09-20"
    assert response.headers["x-payroll-row-count"] == "1"
    period, report_type, employee = calls[0]
    assert period.start.isoformat() == "2026-08-21"
    assert period.end.isoformat() == "2026-09-20"
    assert report_type == "developer"
    assert employee is None

    history = client.get(
        "/api/talentops/v1/payroll/exports/history?year=2026&month=9"
    )
    assert history.status_code == 200
    payload = history.json()
    assert payload["cycle_id"] == "2026-09:2026-08-21:2026-09-20"
    assert payload["start_date"] == "2026-08-21"
    assert payload["end_date"] == "2026-09-20"
    assert payload["items"][0]["exported_by"] == "owner@example.com"
    assert payload["items"][0]["row_count"] == 1
    assert "content" not in payload["items"][0]


def test_payroll_export_api_requires_csrf(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)

    response = client.post(
        "/api/talentops/v1/payroll/exports?year=2026&month=9",
        json={"report_type": "developer"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"
    assert calls == []
