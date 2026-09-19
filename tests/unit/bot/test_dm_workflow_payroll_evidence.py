from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from digital_bast.bot import dm_workflow
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft

_JID = "628123@s.whatsapp.net"
_EMPLOYEE_ID = "MTG-TF/TEST1"
_ATTENDANCE_KEY = "ATT-2026-09-04"


class _WorkflowControl:
    async def resolve_jid(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        return None


class _Activation:
    def __init__(self, employee_id: str | None = _EMPLOYEE_ID) -> None:
        self.employee_id = employee_id

    async def resolve(self, wa_jid: str) -> str | None:
        assert wa_jid == _JID
        return self.employee_id


class _State:
    def __init__(self, draft: AttendanceResolutionDraft) -> None:
        self.draft = draft
        self.cleared = False

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        return self.draft

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True


class _ContextStore:
    async def load(self, wa_jid: str) -> AttendanceReminderContext:
        assert wa_jid == _JID
        return AttendanceReminderContext.create(
            employee_id=_EMPLOYEE_ID,
            cycle_id="2026-09:2026-08-21:2026-09-20",
            attendance_keys=(_ATTENDANCE_KEY,),
            expires_at=datetime(2026, 9, 19, 9, 0, tzinfo=UTC) + timedelta(days=2),
        )


def _draft() -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=_ATTENDANCE_KEY,
        employee_id=_EMPLOYEE_ID,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        work_date=date(2026, 9, 4),
        proposed_check_out=time(17, 40),
        has_evidence=False,
    )


def _patch_base(monkeypatch: pytest.MonkeyPatch, state: _State) -> object:
    evidence = object()
    monkeypatch.setattr(dm_workflow, "create_workflow_control_service", _WorkflowControl)
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_resolution_dm_state_service",
        lambda: state,
    )
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_reminder_context_service",
        _ContextStore,
    )
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_evidence_service",
        lambda: evidence,
    )
    return evidence


@pytest.mark.asyncio
async def test_active_payroll_media_bypasses_legacy_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _State(_draft())
    evidence = _patch_base(monkeypatch, state)
    monkeypatch.setattr(dm_workflow, "create_activation_service", _Activation)
    seen: list[tuple[str, AttendanceResolutionDraft, Path, str, object, _State]] = []

    async def attach(**kwargs: object) -> str:
        seen.append(
            (
                str(kwargs["jid"]),
                kwargs["draft"],
                kwargs["file_path"],
                str(kwargs["caption"]),
                kwargs["evidence"],
                kwargs["state"],
            )
        )
        return "PAYROLL EVIDENCE STORED"

    monkeypatch.setattr(dm_workflow, "attach_payroll_attendance_evidence", attach)

    async def legacy_must_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("active Payroll evidence must not enter legacy selection")

    monkeypatch.setattr(dm_workflow.cli, "bot_evidence", legacy_must_not_run)
    file_path = tmp_path / "bukti.jpg"
    file_path.write_bytes(b"image")

    response = await dm_workflow.evidence(_JID, file_path, "bukti 4 sep")

    assert response == "PAYROLL EVIDENCE STORED"
    assert seen == [(_JID, state.draft, file_path, "bukti 4 sep", evidence, state)]
    assert state.cleared is False


@pytest.mark.asyncio
async def test_identity_change_clears_payroll_draft_before_media_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _State(_draft())
    _patch_base(monkeypatch, state)
    monkeypatch.setattr(
        dm_workflow,
        "create_activation_service",
        lambda: _Activation("MTG-TF/OTHER"),
    )

    async def attach_must_not_run(**_kwargs: object) -> str:
        raise AssertionError("wrong identity must not upload evidence")

    monkeypatch.setattr(dm_workflow, "attach_payroll_attendance_evidence", attach_must_not_run)
    file_path = tmp_path / "bukti.jpg"
    file_path.write_bytes(b"image")

    response = await dm_workflow.evidence(_JID, file_path, "")

    assert state.cleared is True
    assert "tidak cocok dengan identity WhatsApp aktif" in response
