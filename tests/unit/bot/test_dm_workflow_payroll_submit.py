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


class _State:
    def __init__(self) -> None:
        self.draft = AttendanceResolutionDraft(
            attendance_key=_ATTENDANCE_KEY,
            employee_id=_EMPLOYEE_ID,
            resolution_type=ResolutionType.MISSING_CLOCK_OUT,
            work_date=date(2026, 9, 4),
            proposed_check_out=time(17, 40),
            has_evidence=True,
        )

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        return self.draft

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID


class _ContextStore:
    def __init__(self) -> None:
        self.context = AttendanceReminderContext.create(
            employee_id=_EMPLOYEE_ID,
            cycle_id="2026-09:2026-08-21:2026-09-20",
            attendance_keys=(_ATTENDANCE_KEY,),
            expires_at=_NOW + timedelta(days=2),
        )

    async def load(self, wa_jid: str) -> AttendanceReminderContext:
        assert wa_jid == _JID
        return self.context

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID


async def _no_sleep(_seconds: float) -> None:
    return None


def _patch_base(monkeypatch: pytest.MonkeyPatch) -> tuple[_State, _ContextStore]:
    state = _State()
    context_store = _ContextStore()
    monkeypatch.setattr(dm_workflow.anyio, "sleep", _no_sleep)
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
        lambda: context_store,
    )
    return state, context_store


@pytest.mark.parametrize("text", ["payroll_attendance_submit", "ajukan", "1"])
@pytest.mark.asyncio
async def test_ready_payroll_draft_routes_submit_action_before_clock_parser(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
) -> None:
    state, context_store = _patch_base(monkeypatch)
    resolution_service = object()
    routing_service = object()
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_resolution_service",
        lambda: resolution_service,
    )
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_reminder_routing_service",
        lambda: routing_service,
    )
    seen: list[dict[str, object]] = []

    async def submit(**kwargs: object) -> str:
        seen.append(kwargs)
        return "SUBMITTED"

    monkeypatch.setattr(dm_workflow, "submit_payroll_attendance_draft", submit)

    response = await dm_workflow.reply(text, _JID)

    assert response == "SUBMITTED"
    assert len(seen) == 1
    assert seen[0]["jid"] == _JID
    assert seen[0]["draft"] == state.draft
    assert seen[0]["context"] == context_store.context
    assert seen[0]["resolutions"] is resolution_service
    assert seen[0]["routing"] is routing_service
    assert seen[0]["state"] is state
    assert seen[0]["context_store"] is context_store


@pytest.mark.parametrize("text", ["payroll_attendance_edit", "ubah", "2"])
@pytest.mark.asyncio
async def test_ready_payroll_draft_routes_edit_without_submitting(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
) -> None:
    state, _context_store = _patch_base(monkeypatch)
    seen: list[dict[str, object]] = []

    async def edit(**kwargs: object) -> str:
        seen.append(kwargs)
        return "EDITING"

    def submit_service_must_not_run() -> object:
        raise AssertionError("edit must not construct or submit a PMO request")

    monkeypatch.setattr(dm_workflow, "edit_payroll_attendance_draft", edit)
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_resolution_service",
        submit_service_must_not_run,
    )

    response = await dm_workflow.reply(text, _JID)

    assert response == "EDITING"
    assert seen == [{"jid": _JID, "draft": state.draft, "state": state}]
