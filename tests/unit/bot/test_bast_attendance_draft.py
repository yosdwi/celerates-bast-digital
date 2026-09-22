from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from digital_bast.bot import bast_attendance_draft
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.bast_reminder_context import BastReminderContext
from digital_bast.domain.completion import DateRange

if TYPE_CHECKING:
    import pytest

_JID = "628123@c.us"
_EMPLOYEE_ID = "EMP-1"
_KEY = "attendance:2026-09-25:EMP-1"
_MESSAGE_AT = datetime(2026, 9, 25, 2, 0, tzinfo=UTC)


class _State:
    def __init__(self) -> None:
        self.draft: AttendanceResolutionDraft | None = None
        self.saved: AttendanceResolutionDraft | None = None

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft | None:
        assert wa_jid == _JID
        return self.draft

    async def begin(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft:
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        assert attendance_key == _KEY
        self.draft = AttendanceResolutionDraft(
            attendance_key=attendance_key,
            employee_id=employee_id,
            resolution_type=ResolutionType.MISSING_CLOCK_OUT,
            work_date=date(2026, 9, 25),
        )
        return self.draft

    async def save_proposal(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        **kwargs: object,
    ) -> AttendanceResolutionDraft:
        assert self.draft is not None
        assert wa_jid == _JID
        assert employee_id == _EMPLOYEE_ID
        assert attendance_key == _KEY
        assert resolution_type is ResolutionType.MISSING_CLOCK_OUT
        proposed_check_out = cast("time | None", kwargs.get("proposed_check_out"))
        self.saved = replace(
            self.draft,
            proposed_check_out=proposed_check_out,
        )
        return self.saved

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID


class _ContextStore:
    def __init__(self) -> None:
        self.saved: AttendanceReminderContext | None = None

    async def save(self, wa_jid: str, context: AttendanceReminderContext) -> None:
        assert wa_jid == _JID
        self.saved = context

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID


async def test_natural_bast_reply_seeds_single_gap_canonical_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    contexts = _ContextStore()
    context = BastReminderContext(
        employee_id=_EMPLOYEE_ID,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        domains=("attendance", "task"),
        expires_at=_MESSAGE_AT + timedelta(days=7),
    )

    async def candidate(
        employee_id: str,
        period: DateRange,
        work_date: date,
    ) -> object:
        assert employee_id == _EMPLOYEE_ID
        assert work_date == date(2026, 9, 25)
        assert period.start == date(2026, 9, 1)
        return SimpleNamespace(attendance_key=_KEY)

    monkeypatch.setattr(
        bast_attendance_draft,
        "create_attendance_resolution_dm_state_service",
        lambda: state,
    )
    monkeypatch.setattr(
        bast_attendance_draft,
        "create_attendance_reminder_context_service",
        lambda: contexts,
    )
    monkeypatch.setattr(bast_attendance_draft, "_candidate_for_date", candidate)
    monkeypatch.setattr(
        bast_attendance_draft,
        "create_payroll_attendance_natural_interpreter",
        lambda: None,
    )

    response = await bast_attendance_draft.natural_bast_attendance_reply(
        text="25 September pulang 17.31",
        jid=_JID,
        message_at=_MESSAGE_AT,
        context=context,
    )

    assert "sudah tersimpan" in response
    assert state.saved is not None
    assert state.saved.proposed_check_out == time(17, 31)
    assert contexts.saved is not None
    assert contexts.saved.attendance_keys == (_KEY,)
    assert contexts.saved.cycle_id == "2026-10:2026-09-21:2026-10-20"
