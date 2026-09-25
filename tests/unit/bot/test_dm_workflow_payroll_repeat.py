from datetime import UTC, date, datetime, timedelta

import pytest

from digital_bast.bot import dm_workflow
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.payroll_attendance_repeat import PayrollRepeatCommand

_EMPLOYEE_ID = "MTG-TF/TEST1"
_JID = "628123@s.whatsapp.net"
_ATTENDANCE_KEY = "ATT-2026-09-07"
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
            work_date=date(2026, 9, 7),
            has_evidence=False,
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
            attendance_keys=("ATT-2026-09-04", _ATTENDANCE_KEY),
            expires_at=_NOW + timedelta(days=2),
        )

    async def load(self, wa_jid: str) -> AttendanceReminderContext:
        assert wa_jid == _JID
        return self.context


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sama", PayrollRepeatCommand.SAME),
        ("1", PayrollRepeatCommand.SAME),
        ("berbeda", PayrollRepeatCommand.DIFFERENT),
        ("2", PayrollRepeatCommand.DIFFERENT),
    ],
)
@pytest.mark.asyncio
async def test_active_unfilled_payroll_draft_routes_repeat_before_other_parsers(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected: PayrollRepeatCommand,
) -> None:
    state = _State()
    context_store = _ContextStore()
    routing = object()
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
    monkeypatch.setattr(
        dm_workflow,
        "create_attendance_reminder_routing_service",
        lambda: routing,
    )
    seen: list[dict[str, object]] = []

    async def repeat(**kwargs: object) -> str:
        seen.append(kwargs)
        return "REPEAT"

    async def submit_must_not_run(**_kwargs: object) -> str:
        raise AssertionError("same-gap choice must not submit a PMO request")

    monkeypatch.setattr(dm_workflow, "handle_payroll_repeat_command", repeat)
    monkeypatch.setattr(dm_workflow, "submit_payroll_attendance_draft", submit_must_not_run)

    response = await dm_workflow.reply(text, _JID)

    assert response == "REPEAT"
    assert len(seen) == 1
    assert seen[0]["command"] is expected
    assert seen[0]["jid"] == _JID
    assert seen[0]["draft"] == state.draft
    assert seen[0]["context"] == context_store.context
    assert seen[0]["state"] is state
    assert seen[0]["routing"] is routing
