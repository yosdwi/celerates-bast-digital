from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from digital_bast.bot.attendance_context import (
    AttendanceReminderContext,
    AttendanceReminderContextService,
)

_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_CONTEXT_ID = UUID("00000000-0000-0000-0000-000000000007")


def _context(*, expires_at: datetime | None = None) -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        "employee-1",
        "2026-09:2026-08-21:2026-09-20",
        ("attendance:first", "attendance:second"),
        expires_at or (_NOW + timedelta(hours=4)),
        context_id=_CONTEXT_ID,
    )


class _FakeCursor:
    def __init__(self, row: object | None = None) -> None:
        self.row = row
        self.statements: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] | None = None,
    ) -> _FakeCursor:
        self.statements.append((statement, parameters))
        return self

    def fetchone(self) -> object | None:
        return self.row


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self, **_kwargs: object) -> _FakeCursor:
        return self._cursor


def _service(
    cursor: _FakeCursor,
    monkeypatch: pytest.MonkeyPatch,
) -> AttendanceReminderContextService:
    service = AttendanceReminderContextService("postgresql://unused")
    monkeypatch.setattr(service, "_connect", lambda: _FakeConnection(cursor))
    return service


def test_snapshot_keeps_the_exact_sent_order_for_number_replies() -> None:
    context = _context()

    assert context.attendance_key_at(1) == "attendance:first"
    assert context.attendance_key_at(2) == "attendance:second"
    assert context.attendance_key_at(0) is None
    assert context.attendance_key_at(3) is None


def test_snapshot_rejects_ambiguous_or_invalid_identity_lists() -> None:
    expires_at = _NOW + timedelta(hours=1)

    with pytest.raises(ValueError, match="must not be empty"):
        AttendanceReminderContext.create("employee-1", "cycle-1", (), expires_at)
    with pytest.raises(ValueError, match="must be unique"):
        AttendanceReminderContext.create(
            "employee-1",
            "cycle-1",
            ("attendance:a", "attendance:a"),
            expires_at,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        AttendanceReminderContext.create(
            "employee-1",
            "cycle-1",
            ("attendance:a",),
            datetime(2026, 9, 19, 12, 0),  # noqa: DTZ001
        )


def test_load_preserves_order_and_fails_closed_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        context_id=_CONTEXT_ID,
        version=1,
        employee_id="employee-1",
        cycle_id="cycle-1",
        attendance_keys=["attendance:first", "attendance:second"],
        expires_at=_NOW + timedelta(minutes=30),
    )
    service = _service(_FakeCursor(row), monkeypatch)

    loaded = service._load("62812@c.us", _NOW)

    assert loaded is not None
    assert loaded.context_id == _CONTEXT_ID
    assert loaded.attendance_keys == ("attendance:first", "attendance:second")
    assert loaded.attendance_key_at(2) == "attendance:second"
    assert service._load("62812@c.us", _NOW + timedelta(hours=1)) is None


def test_load_fails_closed_for_corrupt_key_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(
        context_id=_CONTEXT_ID,
        version=1,
        employee_id="employee-1",
        cycle_id="cycle-1",
        attendance_keys={"not": "an array"},
        expires_at=_NOW + timedelta(minutes=30),
    )
    service = _service(_FakeCursor(row), monkeypatch)

    assert service._load("62812@c.us", _NOW) is None


def test_save_does_not_touch_legacy_or_navigation_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor()
    service = _service(cursor, monkeypatch)

    service._save("62812@c.us", _context())

    statement, parameters = cursor.statements[-1]
    assert "attendance_context_keys" in statement
    assert "talent_context_" not in statement
    assert "updated_at" not in statement
    assert parameters is not None
    assert parameters[0] == "62812@c.us"
    assert parameters[1] == _CONTEXT_ID


def test_clear_only_removes_attendance_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor()
    service = _service(cursor, monkeypatch)

    service._clear("62812@c.us")

    statement, parameters = cursor.statements[-1]
    assert "attendance_context_id = NULL" in statement
    assert "attendance_context_keys = NULL" in statement
    assert "talent_context_" not in statement
    assert "pending_task" not in statement
    assert parameters == ("62812@c.us",)
