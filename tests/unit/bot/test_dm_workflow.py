from pathlib import Path

import pytest

from digital_bast.bot import dm_workflow
from digital_bast.bot.attendance_resolution import (
    ResolutionType,
    SubmitOutcome,
    SubmitResult,
)
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft

_JID = "628123@s.whatsapp.net"
_EMPLOYEE_ID = "MTG-TF/TEST1"
_ATTENDANCE_KEY = "ATT-1"


class _FakeState:
    def __init__(self, draft: AttendanceResolutionDraft | None) -> None:
        self.draft = draft
        self.cleared = False
        self.marked: tuple[str, str, str] | None = None

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft | None:
        assert wa_jid == _JID
        return self.draft

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True
        self.draft = None

    async def mark_evidence_ready(
        self, wa_jid: str, employee_id: str, attendance_key: str
    ) -> AttendanceResolutionDraft | None:
        self.marked = (wa_jid, employee_id, attendance_key)
        return self.draft


class _FakeActivation:
    def __init__(self, employee_id: str | None = _EMPLOYEE_ID) -> None:
        self.employee_id = employee_id

    async def resolve(self, wa_jid: str) -> str | None:
        assert wa_jid == _JID
        return self.employee_id


class _FakeResolutionService:
    def __init__(self, outcomes: list[SubmitOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[ResolutionType] = []

    async def submit(
        self,
        employee_id: str,
        attendance_key: str,
        requested_by_jid: str,
        resolution_type: ResolutionType,
        **kwargs: object,
    ) -> SubmitResult:
        assert employee_id == _EMPLOYEE_ID
        assert attendance_key == _ATTENDANCE_KEY
        assert requested_by_jid == _JID
        self.calls.append(resolution_type)
        return SubmitResult(self.outcomes.pop(0))


class _FakeAttendanceEvidence:
    def __init__(self, pending_key: str | None) -> None:
        self.pending_key = pending_key

    async def pending_attendance(self, wa_jid: str) -> str | None:
        assert wa_jid == _JID
        return self.pending_key


def _draft(resolution_type: ResolutionType) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(_ATTENDANCE_KEY, _EMPLOYEE_ID, resolution_type)


@pytest.mark.asyncio
async def test_reply_without_resolution_draft_preserves_legacy_dm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(None)
    monkeypatch.setattr(
        dm_workflow, "create_attendance_resolution_dm_state_service", lambda: state
    )
    monkeypatch.setattr(
        dm_workflow.cli,
        "bot_reply",
        lambda text, *, jid, channel: f"legacy:{channel}:{jid}:{text}",
    )

    result = await dm_workflow.reply("tasklist", _JID)

    assert result == f"legacy:dm:{_JID}:tasklist"


@pytest.mark.asyncio
async def test_active_resolution_draft_blocks_legacy_task_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(_draft(ResolutionType.MISSING_CLOCK_OUT))
    monkeypatch.setattr(
        dm_workflow, "create_attendance_resolution_dm_state_service", lambda: state
    )
    monkeypatch.setattr(dm_workflow, "create_activation_service", _FakeActivation)

    def legacy_must_not_run(*args: object, **kwargs: object) -> str:
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(dm_workflow.cli, "bot_reply", legacy_must_not_run)

    result = await dm_workflow.reply("CCTV Gate 2", _JID)

    assert "Clock Out masih kosong" in result
    assert state.cleared is False


@pytest.mark.asyncio
async def test_single_clock_falls_through_source_validation_until_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(_draft(ResolutionType.MISSING_CLOCK_OUT))
    resolutions = _FakeResolutionService(
        [SubmitOutcome.SOURCE_NOT_ELIGIBLE, SubmitOutcome.CREATED]
    )
    monkeypatch.setattr(
        dm_workflow, "create_attendance_resolution_dm_state_service", lambda: state
    )
    monkeypatch.setattr(dm_workflow, "create_activation_service", _FakeActivation)
    monkeypatch.setattr(dm_workflow, "create_attendance_resolution_service", lambda: resolutions)

    result = await dm_workflow.reply("17:23", _JID)

    assert resolutions.calls == [
        ResolutionType.MISSING_CLOCK_IN,
        ResolutionType.MISSING_CLOCK_OUT,
    ]
    assert "Menunggu approval" in result
    assert "tidak diubah" in result
    assert state.cleared is True


@pytest.mark.asyncio
async def test_identity_change_clears_stale_draft_and_returns_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(_draft(ResolutionType.MISSING_CLOCK_IN))
    monkeypatch.setattr(
        dm_workflow, "create_attendance_resolution_dm_state_service", lambda: state
    )
    monkeypatch.setattr(
        dm_workflow, "create_activation_service", lambda: _FakeActivation("MTG-TF/OTHER")
    )
    monkeypatch.setattr(
        dm_workflow.cli,
        "bot_reply",
        lambda text, *, jid, channel: f"legacy:{channel}:{jid}:{text}",
    )

    result = await dm_workflow.reply("halo", _JID)

    assert state.cleared is True
    assert result == f"legacy:dm:{_JID}:halo"


@pytest.mark.asyncio
async def test_media_is_not_rerouted_while_resolution_draft_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(_draft(ResolutionType.MISSING_CLOCK_IN))
    monkeypatch.setattr(
        dm_workflow, "create_attendance_resolution_dm_state_service", lambda: state
    )

    async def legacy_evidence_must_not_run(*args: object, **kwargs: object) -> str:
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(dm_workflow.cli, "bot_evidence", legacy_evidence_must_not_run)

    result = await dm_workflow.evidence(_JID, Path("unused.jpg"), "task evidence")

    assert "Clock In masih kosong" in result


@pytest.mark.asyncio
async def test_successful_legacy_attendance_upload_opens_resolution_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _draft(ResolutionType.MISSING_CLOCK_OUT)
    state = _FakeState(None)
    attendance = _FakeAttendanceEvidence(_ATTENDANCE_KEY)
    monkeypatch.setattr(
        dm_workflow, "create_attendance_resolution_dm_state_service", lambda: state
    )
    monkeypatch.setattr(dm_workflow, "create_activation_service", _FakeActivation)
    monkeypatch.setattr(
        dm_workflow, "create_attendance_evidence_service", lambda: attendance
    )

    async def legacy_evidence(jid: str, file_path: Path, caption: str) -> str:
        assert jid == _JID
        assert file_path == Path("evidence.jpg")
        assert caption == "bukti"
        return "✅ Evidence tersimpan."

    async def mark_ready(
        wa_jid: str, employee_id: str, attendance_key: str
    ) -> AttendanceResolutionDraft:
        state.marked = (wa_jid, employee_id, attendance_key)
        return draft

    state.mark_evidence_ready = mark_ready  # type: ignore[method-assign]
    monkeypatch.setattr(dm_workflow.cli, "bot_evidence", legacy_evidence)

    result = await dm_workflow.evidence(_JID, Path("evidence.jpg"), "bukti")

    assert state.marked == (_JID, _EMPLOYEE_ID, _ATTENDANCE_KEY)
    assert "Evidence tersimpan" in result
    assert "Clock Out masih kosong" in result
