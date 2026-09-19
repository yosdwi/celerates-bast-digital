from datetime import UTC, date, datetime, time, timedelta

import pytest

from digital_bast.bot import dm_workflow
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft

_JID = "628123@s.whatsapp.net"
_EMPLOYEE_ID = "MTG-TF/TEST1"
_ATTENDANCE_KEY = "ATT-2026-09-04"
_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)


class _WorkflowControl:
    async def resolve_jid(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        return None


class _Activation:
    async def resolve(self, wa_jid: str) -> str:
        assert wa_jid == _JID
        return _EMPLOYEE_ID


class _ContextStore:
    def __init__(self, context: AttendanceReminderContext) -> None:
        self.context = context

    async def load(self, wa_jid: str) -> AttendanceReminderContext:
        assert wa_jid == _JID
        return self.context


class _State:
    def __init__(
        self,
        draft: AttendanceResolutionDraft,
        saved: AttendanceResolutionDraft | None,
    ) -> None:
        self.draft = draft
        self.saved = saved
        self.calls: list[tuple[ResolutionType, time | None, time | None]] = []
        self.cleared = False

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        return self.draft

    async def save_proposal(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: object | None = None,
    ) -> AttendanceResolutionDraft | None:
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        assert attendance_key == _ATTENDANCE_KEY
        assert absence_type is None
        self.calls.append((resolution_type, proposed_check_in, proposed_check_out))
        return self.saved

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared = True


def _context() -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        employee_id=_EMPLOYEE_ID,
        cycle_id="2026-09:2026-08-21:2026-09-20",
        attendance_keys=(_ATTENDANCE_KEY,),
        expires_at=_NOW + timedelta(days=2),
    )


def _draft(*, has_evidence: bool = False) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=_ATTENDANCE_KEY,
        employee_id=_EMPLOYEE_ID,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        work_date=date(2026, 9, 4),
        has_evidence=has_evidence,
    )


def _saved(*, has_evidence: bool = False) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=_ATTENDANCE_KEY,
        employee_id=_EMPLOYEE_ID,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        work_date=date(2026, 9, 4),
        proposed_check_out=time(17, 40),
        has_evidence=has_evidence,
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    state: _State,
) -> None:
    monkeypatch.setattr(dm_workflow, "create_workflow_control_service", _WorkflowControl)
    monkeypatch.setattr(dm_workflow, "create_activation_service", _Activation)
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_resolution_dm_state_service",
        lambda: state,
    )
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_reminder_context_service",
        lambda: _ContextStore(_context()),
    )

    def resolution_service_must_not_run() -> object:
        raise AssertionError("Payroll P10 must not submit a PMO request")

    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_resolution_service",
        resolution_service_must_not_run,
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(dm_workflow.anyio, "sleep", no_sleep)


@pytest.mark.asyncio
async def test_payroll_clock_reply_is_saved_before_evidence_without_pmo_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(_draft(), _saved())
    _patch(monkeypatch, state)

    response = await dm_workflow.reply("17.40", _JID)

    assert state.calls == [(ResolutionType.MISSING_CLOCK_OUT, None, time(17, 40))]
    assert "Clock Out: 17:40" in response
    assert "kirim screenshot/bukti attendance" in response
    assert "Menunggu approval" not in response
    assert state.cleared is False


@pytest.mark.asyncio
async def test_existing_evidence_skips_the_evidence_request_but_does_not_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(_draft(has_evidence=True), _saved(has_evidence=True))
    _patch(monkeypatch, state)

    response = await dm_workflow.reply("17:40", _JID)

    assert "Bukti: ✓" in response
    assert "Belum diajukan ke PMO" in response
    assert "kirim screenshot/bukti" not in response


@pytest.mark.asyncio
async def test_stale_source_clears_only_the_draft_and_keeps_reminder_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State(_draft(), None)
    _patch(monkeypatch, state)

    response = await dm_workflow.reply("17:40", _JID)

    assert state.cleared is True
    assert "draft ini tidak disimpan" in response
    assert "lengkapi" in response
