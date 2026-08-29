from __future__ import annotations

import json
from datetime import date, datetime, time
from types import SimpleNamespace
from uuid import UUID

import pytest

from digital_bast.bot import talent_home
from digital_bast.bot.attendance_resolution import (
    AttendanceResolution,
    ResolutionStatus,
    ResolutionType,
)
from digital_bast.domain.completion import CheckResult, CheckState, DateRange, EmployeeCompletion
from digital_bast.domain.time import JAKARTA

_EMPLOYEE_ID = "MTG-TF/TEST1"
_PERIOD = DateRange(date(2026, 8, 1), date(2026, 8, 29))


def _employee(*, complete: bool = False) -> EmployeeCompletion:
    if complete:
        ok = CheckResult(CheckState.COMPLETE, ())
        return EmployeeCompletion(
            employee_id=_EMPLOYEE_ID,
            name="Putra Tama",
            timesheet=ok,
            task_list=ok,
            evidence=ok,
            log_1_pama=ok,
            total_tasks=2,
            total_work_days=20,
        )
    return EmployeeCompletion(
        employee_id=_EMPLOYEE_ID,
        name="Putra Tama",
        timesheet=CheckResult(CheckState.COMPLETE, ()),
        task_list=CheckResult(CheckState.COMPLETE, ()),
        evidence=CheckResult(
            CheckState.INCOMPLETE,
            ("Task CCTV belum ada evidence.", "Task Report belum ada evidence."),
        ),
        log_1_pama=CheckResult(
            CheckState.INCOMPLETE,
            ("27 Agustus — Clock Out belum terisi.",),
        ),
        total_tasks=2,
        total_work_days=20,
    )


def _request(
    status: ResolutionStatus,
    *,
    rejected_reason: str | None = None,
) -> AttendanceResolution:
    return AttendanceResolution(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        attendance_id=1,
        employee_id=_EMPLOYEE_ID,
        nrp="JIMT24002",
        full_name="Putra Tama",
        work_date=date(2026, 8, 27),
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        absence_type=None,
        proposed_check_in=None,
        proposed_check_out=time(17, 23),
        status=status,
        evidence_id=UUID("22222222-2222-4222-8222-222222222222"),
        requested_by_jid="628123@s.whatsapp.net",
        submitted_at=datetime(2026, 8, 27, 18, 0, tzinfo=JAKARTA),
        reviewed_by="pmo@example.com" if status is not ResolutionStatus.PENDING else None,
        reviewed_at=datetime(2026, 8, 28, 14, 22, tzinfo=JAKARTA)
        if status is not ResolutionStatus.PENDING
        else None,
        rejection_reason=rejected_reason,
    )


class _ResolutionService:
    def __init__(self, items: tuple[AttendanceResolution, ...]) -> None:
        self.items = items

    async def for_employee(self, employee_id: str) -> tuple[AttendanceResolution, ...]:
        assert employee_id == _EMPLOYEE_ID
        return self.items


def _payload(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


@pytest.fixture(autouse=True)
def _fixed_period(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(talent_home, "_period_now", lambda: _PERIOD)


@pytest.mark.asyncio
async def test_home_is_three_action_native_button_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    async def completion(_period: DateRange) -> object:
        return SimpleNamespace(employees=(_employee(),))

    monkeypatch.setattr(talent_home, "completion_status", completion)

    payload = _payload(await talent_home.home(_EMPLOYEE_ID))
    actions = payload["actions"]
    assert isinstance(actions, list)
    assert [item["id"] for item in actions] == ["status", "attendance", "tasklist"]
    assert "Attendance : 1 perlu tindakan" in str(payload["text"])
    assert "Evidence   : 2 belum lengkap" in str(payload["text"])


@pytest.mark.asyncio
async def test_complete_home_says_bast_is_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    async def completion(_period: DateRange) -> object:
        return SimpleNamespace(employees=(_employee(complete=True),))

    monkeypatch.setattr(talent_home, "completion_status", completion)

    payload = _payload(await talent_home.home(_EMPLOYEE_ID))

    assert "BAST kamu sudah lengkap" in str(payload["text"])


@pytest.mark.asyncio
async def test_status_surfaces_request_entry_and_pending_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def completion(_period: DateRange) -> object:
        return SimpleNamespace(employees=(_employee(),))

    monkeypatch.setattr(talent_home, "completion_status", completion)
    monkeypatch.setattr(
        talent_home,
        "create_attendance_resolution_service",
        lambda: _ResolutionService((_request(ResolutionStatus.PENDING),)),
    )

    payload = _payload(await talent_home.status(_EMPLOYEE_ID))
    actions = payload["actions"]
    assert isinstance(actions, list)
    assert actions[0]["id"] == "requests"
    assert "Request PMO: 1 pending" in str(payload["text"])


@pytest.mark.asyncio
async def test_request_history_shows_rejection_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        talent_home,
        "create_attendance_resolution_service",
        lambda: _ResolutionService(
            (_request(ResolutionStatus.REJECTED, rejected_reason="Evidence tidak sesuai"),)
        ),
    )

    payload = _payload(await talent_home.requests(_EMPLOYEE_ID))

    assert "Rejected" in str(payload["text"])
    assert "Evidence tidak sesuai" in str(payload["text"])
    actions = payload["actions"]
    assert isinstance(actions, list)
    assert len(actions) == 3


def test_free_text_aliases_are_deterministic() -> None:
    assert talent_home.looks_like_status("status saya") is True
    assert talent_home.looks_like_requests("pengajuan saya") is True
    assert talent_home.looks_like_status("tolong jelaskan status project") is False
