from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from digital_bast.application.bast_workflow import (
    BastBlocker,
    BastGenerationMode,
    BastReadiness,
)
from digital_bast.application.workflow_control import (
    WorkflowOperator,
    WorkflowRole,
)
from digital_bast.bot import pmo_bast
from digital_bast.domain.completion import DateRange
from digital_bast.domain.models import EmployeeRole

_FIXED_PERIOD = DateRange(date(2026, 8, 1), date(2026, 8, 31))


def _operator(*, can_generate: bool = True) -> WorkflowOperator:
    return WorkflowOperator(
        email="pmo@example.com",
        display_name="PMO Test",
        role=WorkflowRole.PMO,
        scope_key="default",
        active=True,
        can_approve_attendance=True,
        can_approve_rebind=True,
        can_generate_bast=can_generate,
        whatsapp_notify=True,
        whatsapp_jid="628111@s.whatsapp.net",
    )


def _readiness(*, ready: bool) -> BastReadiness:
    blockers = () if ready else (
        BastBlocker(
            employee_id="employee-1",
            nrp="JIMT24002",
            name="Talent Test",
            domain="attendance",
            state="incomplete",
            issues=("Missing Clock Out",),
        ),
        BastBlocker(
            employee_id="employee-1",
            nrp="JIMT24002",
            name="Talent Test",
            domain="evidence",
            state="incomplete",
            issues=("Task evidence missing",),
        ),
    )
    return BastReadiness(
        report_type="developer",
        role=EmployeeRole.DEVELOPER,
        total_talents=2,
        ready_talents=2 if ready else 1,
        ready=ready,
        blockers=blockers,
    )


class Workflow:
    def __init__(self, readiness: BastReadiness) -> None:
        self.value = readiness
        self.audit: list[dict[str, Any]] = []

    async def readiness(self, period: DateRange, report_type: str) -> BastReadiness:
        assert period == _FIXED_PERIOD
        assert report_type == "developer"
        return self.value

    async def record_generation(self, **kwargs: Any) -> UUID:
        self.audit.append(kwargs)
        return UUID("11111111-1111-4111-8111-111111111111")


def _payload(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


@pytest.mark.asyncio
async def test_bast_root_is_button_first_team_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pmo_bast, "_period_now", lambda: _FIXED_PERIOD)

    payload = _payload(await pmo_bast.reply(_operator(), "pmo:bast"))

    assert payload["kind"] == "interactive"
    assert [item["id"] for item in payload["actions"]] == [
        "pmo:bast:developer",
        "pmo:bast:iotoperation",
        "pmo:menu",
    ]


@pytest.mark.asyncio
async def test_blocked_bast_offers_preview_and_two_step_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = Workflow(_readiness(ready=False))
    monkeypatch.setattr(pmo_bast, "_period_now", lambda: _FIXED_PERIOD)
    monkeypatch.setattr(pmo_bast, "_bast_service", lambda: workflow)

    status = _payload(await pmo_bast.reply(_operator(), "pmo:bast:developer"))
    confirmation = _payload(await pmo_bast.reply(_operator(), "pmo:bast:developer:force"))

    assert "1 / 2" in status["text"]
    assert "1 Attendance blocker" in status["text"]
    assert "1 Evidence blocker" in status["text"]
    assert [item["id"] for item in status["actions"]] == [
        "pmo:bast:developer:preview",
        "pmo:bast:developer:force",
        "pmo:bast",
    ]
    assert "Tetap generate Final" in confirmation["text"]
    assert confirmation["actions"][0]["id"] == "pmo:bast:developer:confirm-force"


@pytest.mark.asyncio
async def test_blocked_final_does_not_generate_without_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = Workflow(_readiness(ready=False))
    calls = 0

    async def generate(_period: DateRange, _report_type: str) -> tuple[Path, object]:
        nonlocal calls
        calls += 1
        raise AssertionError("blocked Final must not generate")

    monkeypatch.setattr(pmo_bast, "_period_now", lambda: _FIXED_PERIOD)
    monkeypatch.setattr(pmo_bast, "_bast_service", lambda: workflow)
    monkeypatch.setattr(pmo_bast, "generate_bast_artifact", generate)

    result = _payload(await pmo_bast.reply(_operator(), "pmo:bast:developer:generate"))

    assert result["kind"] == "interactive"
    assert calls == 0
    assert workflow.audit == []


@pytest.mark.asyncio
async def test_force_confirm_generates_to_dm_and_records_forced_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow = Workflow(_readiness(ready=False))
    artifact = tmp_path / "BAST_developer_2026-08.pdf"
    artifact.write_bytes(b"pdf")

    async def generate(period: DateRange, report_type: str) -> tuple[Path, object]:
        assert period == _FIXED_PERIOD
        assert report_type == "developer"
        report = SimpleNamespace(fingerprint="fingerprint-1")
        return artifact, report

    monkeypatch.setattr(pmo_bast, "_period_now", lambda: _FIXED_PERIOD)
    monkeypatch.setattr(pmo_bast, "_bast_service", lambda: workflow)
    monkeypatch.setattr(pmo_bast, "generate_bast_artifact", generate)

    payload = _payload(
        await pmo_bast.reply(_operator(), "pmo:bast:developer:confirm-force")
    )

    assert payload["kind"] == "file"
    assert payload["path"] == str(artifact)
    assert "Force Generate" in payload["caption"]
    assert len(workflow.audit) == 1
    audit = workflow.audit[0]
    assert audit["mode"] is BastGenerationMode.FINAL
    assert audit["forced"] is True
    assert audit["generated_by"] == "pmo@example.com"
    assert audit["force_reason"] == "Confirmed via PMO WhatsApp after readiness warning"


@pytest.mark.asyncio
async def test_ready_final_is_not_marked_forced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow = Workflow(_readiness(ready=True))
    artifact = tmp_path / "BAST_developer_2026-08.pdf"
    artifact.write_bytes(b"pdf")

    async def generate(_period: DateRange, _report_type: str) -> tuple[Path, object]:
        return artifact, SimpleNamespace(fingerprint="fingerprint-ready")

    monkeypatch.setattr(pmo_bast, "_period_now", lambda: _FIXED_PERIOD)
    monkeypatch.setattr(pmo_bast, "_bast_service", lambda: workflow)
    monkeypatch.setattr(pmo_bast, "generate_bast_artifact", generate)

    payload = _payload(await pmo_bast.reply(_operator(), "pmo:bast:developer:generate"))

    assert payload["kind"] == "file"
    assert len(workflow.audit) == 1
    assert workflow.audit[0]["mode"] is BastGenerationMode.FINAL
    assert workflow.audit[0]["forced"] is False
    assert workflow.audit[0]["force_reason"] is None


@pytest.mark.asyncio
async def test_generation_permission_is_enforced_in_dm(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = Workflow(_readiness(ready=True))
    monkeypatch.setattr(pmo_bast, "_period_now", lambda: _FIXED_PERIOD)
    monkeypatch.setattr(pmo_bast, "_bast_service", lambda: workflow)

    result = await pmo_bast.reply(
        _operator(can_generate=False),
        "pmo:bast:developer:preview",
    )

    assert result == "Akun PMO ini tidak punya permission generate BAST."
    assert workflow.audit == []
