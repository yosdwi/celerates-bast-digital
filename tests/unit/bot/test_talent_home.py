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
from digital_bast.bot.evidence import EvidenceCandidate
from digital_bast.domain.completion import CheckResult, CheckState, DateRange, EmployeeCompletion
from digital_bast.domain.time import JAKARTA

_EMPLOYEE_ID = "MTG-TF/TEST1"
_PERIOD = DateRange(date(2026, 8, 1), date(2026, 8, 29))


def _employee(
    *,
    complete: bool = False,
    attendance_action: bool = True,
    missing_data: bool = True,
) -> EmployeeCompletion:
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
    evidence_days = (date(2026, 8, 27),) if attendance_action else ()
    missing_days = (date(2026, 8, 28),) if missing_data else ()
    attendance_issues = tuple(
        item
        for item in (
            "27 Agustus — Clock Out belum terisi." if attendance_action else None,
            "28 Agustus — Data attendance belum tersedia." if missing_data else None,
        )
        if item is not None
    )
    return EmployeeCompletion(
        employee_id=_EMPLOYEE_ID,
        name="Putra Tama",
        timesheet=CheckResult(CheckState.COMPLETE, ()),
        task_list=CheckResult(CheckState.COMPLETE, ()),
        evidence=CheckResult(
            CheckState.INCOMPLETE,
            ("Task CCTV belum ada evidence.",),
        ),
        log_1_pama=CheckResult(CheckState.INCOMPLETE, attendance_issues),
        total_tasks=2,
        total_work_days=20,
        log_1_pama_evidence_days=evidence_days,
        log_1_pama_missing_data_days=missing_days,
    )


def _request(
    status: ResolutionStatus,
    *,
    rejected_reason: str | None = None,
    submitted_hour: int = 18,
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
        submitted_at=datetime(2026, 8, 27, submitted_hour, 0, tzinfo=JAKARTA),
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


class _EvidenceService:
    def __init__(self, items: tuple[EvidenceCandidate, ...]) -> None:
        self.items = items

    async def list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        assert employee_id == _EMPLOYEE_ID
        return self.items


def _task(*, evidence_count: int, day: int = 20) -> EvidenceCandidate:
    return EvidenceCandidate(
        "redmine",
        f"task-{day}",
        f"Task {day}",
        date(2026, 8, day),
        evidence_count,
    )


def _payload(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


def _patch_home_services(
    monkeypatch: pytest.MonkeyPatch,
    employee: EmployeeCompletion,
    *,
    requests: tuple[AttendanceResolution, ...] = (),
    tasks: tuple[EvidenceCandidate, ...] = (),
) -> None:
    async def completion(_period: DateRange) -> object:
        return SimpleNamespace(employees=(employee,))

    monkeypatch.setattr(talent_home, "completion_status", completion)
    monkeypatch.setattr(
        talent_home,
        "create_attendance_resolution_service",
        lambda: _ResolutionService(requests),
    )
    monkeypatch.setattr(talent_home, "create_evidence_service", lambda: _EvidenceService(tasks))


@pytest.fixture(autouse=True)
def _fixed_period(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(talent_home, "_period_now", lambda: _PERIOD)


@pytest.mark.asyncio
async def test_home_is_three_action_workspace_entry_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_home_services(
        monkeypatch,
        _employee(),
        tasks=(_task(evidence_count=0), _task(evidence_count=1, day=21)),
    )

    payload = _payload(await talent_home.home(_EMPLOYEE_ID))
    actions = payload["actions"]
    assert isinstance(actions, list)
    assert [item["id"] for item in actions] == ["bast-saya", "attendance", "tasklist"]
    text = str(payload["text"])
    assert "Perlu tindakan     : 2" in text
    assert "Menunggu PMO       : 0" in text
    assert "Data belum tersedia: 1" in text


@pytest.mark.asyncio
async def test_home_prepends_binding_confirmation_without_changing_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_home_services(monkeypatch, _employee(), tasks=())

    payload = _payload(
        await talent_home.home(_EMPLOYEE_ID, greeting="✅ Terhubung sebagai Yoses.")
    )
    text = str(payload["text"])
    assert text.startswith("✅ Terhubung sebagai Yoses.\n\nHalo")
    assert [item["id"] for item in payload["actions"]] == [
        "bast-saya",
        "attendance",
        "tasklist",
    ]


@pytest.mark.asyncio
async def test_complete_home_says_no_talent_action(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_home_services(monkeypatch, _employee(complete=True), tasks=(_task(evidence_count=1),))

    payload = _payload(await talent_home.home(_EMPLOYEE_ID))

    assert "Tidak ada tindakan yang perlu kamu lakukan" in str(payload["text"])


@pytest.mark.asyncio
async def test_home_distinguishes_pending_from_talent_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_home_services(
        monkeypatch,
        _employee(attendance_action=False, missing_data=False),
        requests=(_request(ResolutionStatus.PENDING),),
        tasks=(_task(evidence_count=1),),
    )

    payload = _payload(await talent_home.home(_EMPLOYEE_ID))
    text = str(payload["text"])
    assert "Perlu tindakan     : 0" in text
    assert "Menunggu PMO       : 1" in text
    assert "Bagian kamu sudah selesai" in text


@pytest.mark.asyncio
async def test_latest_rejected_attendance_returns_to_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_home_services(
        monkeypatch,
        _employee(attendance_action=False, missing_data=False),
        requests=(_request(ResolutionStatus.REJECTED, rejected_reason="Evidence tidak sesuai"),),
        tasks=(),
    )

    payload = _payload(await talent_home.home(_EMPLOYEE_ID))

    assert "Perlu tindakan     : 1" in str(payload["text"])


@pytest.mark.asyncio
async def test_status_surfaces_ownership_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_home_services(
        monkeypatch,
        _employee(),
        requests=(_request(ResolutionStatus.PENDING),),
        tasks=(_task(evidence_count=0),),
    )

    payload = _payload(await talent_home.status(_EMPLOYEE_ID))
    text = str(payload["text"])
    assert "Attendance       : 1 perlu tindakan" in text
    assert "Task & Evidence  : 1 perlu dilengkapi" in text
    assert "Menunggu PMO     : 1" in text
    assert "Data unavailable : 1" in text


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
    assert [item["id"] for item in actions] == ["bast-saya", "attendance", "tasklist"]


def test_free_text_aliases_remain_exact_not_substring_matches() -> None:
    assert talent_home.looks_like_status("status saya") is True
    assert talent_home.looks_like_requests("pengajuan saya") is True
    assert talent_home.looks_like_status("tolong jelaskan status project") is False
