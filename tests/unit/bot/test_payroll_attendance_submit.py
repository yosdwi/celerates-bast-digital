from datetime import UTC, date, datetime, time

import pytest

from digital_bast.application.attendance_closing import (
    AttendanceClosingReason,
    AttendanceClosingStatus,
    AttendanceScheduleState,
    AttendanceSourceState,
)
from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_read import PayrollDayView
from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderGapSelection,
    AttendanceReminderRouteResult,
    AttendanceReminderRouteStatus,
)
from digital_bast.bot.attendance_resolution import ResolutionType, SubmitOutcome, SubmitResult
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.payroll_attendance_draft import (
    PAYROLL_DRAFT_EDIT_ACTION_ID,
    PAYROLL_DRAFT_SUBMIT_ACTION_ID,
    PayrollDraftCommand,
    parse_payroll_draft_command,
    render_payroll_draft_prompt,
)
from digital_bast.bot.payroll_attendance_submit import (
    edit_payroll_attendance_draft,
    submit_payroll_attendance_draft,
)

_JID = "628123@s.whatsapp.net"
_EMPLOYEE_ID = "MTG-TF/TEST1"
_FIRST_KEY = "ATT-2026-09-04"
_NEXT_KEY = "ATT-2026-09-07"
_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
_CYCLE_ID = "2026-09:2026-08-21:2026-09-20"


def _context() -> AttendanceReminderContext:
    return AttendanceReminderContext.create(
        employee_id=_EMPLOYEE_ID,
        cycle_id=_CYCLE_ID,
        attendance_keys=(_FIRST_KEY, _NEXT_KEY),
        expires_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


def _draft(
    attendance_key: str = _FIRST_KEY,
    *,
    proposal: bool = True,
    evidence: bool = True,
) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=attendance_key,
        employee_id=_EMPLOYEE_ID,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        work_date=date(2026, 9, 4 if attendance_key == _FIRST_KEY else 7),
        proposed_check_out=time(17, 40) if proposal else None,
        has_evidence=evidence,
    )


def _next_selection() -> AttendanceReminderGapSelection:
    day = PayrollDayView(
        attendance_id=2,
        attendance_key=_NEXT_KEY,
        work_date=date(2026, 9, 7),
        schedule_state=AttendanceScheduleState.WORKING,
        source_state=AttendanceSourceState.AVAILABLE,
        raw_check_in="07:30",
        raw_check_out=None,
        proposed_check_in=None,
        proposed_check_out=None,
        resolution_id=None,
        resolution_status=None,
        resolution_type=None,
        absence_type=None,
        rejection_reason=None,
        has_evidence=False,
        status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
        reason=AttendanceClosingReason.GAP_UNCOVERED,
        talent_action_required=True,
    )
    return AttendanceReminderGapSelection(payroll_cycle(2026, 9), day, 1)


class _ResolutionService:
    def __init__(self, outcome: SubmitOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, str, ResolutionType, time | None]] = []

    async def submit(
        self,
        employee_id: str,
        attendance_key: str,
        requested_by_jid: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: object | None = None,
    ) -> SubmitResult:
        assert proposed_check_in is None
        assert absence_type is None
        self.calls.append(
            (employee_id, attendance_key, requested_by_jid, resolution_type, proposed_check_out)
        )
        return SubmitResult(self.outcome)


class _State:
    def __init__(self, begin_result: AttendanceResolutionDraft | None = None) -> None:
        self.begin_result = begin_result
        self.cleared = 0
        self.begins: list[tuple[str, str, str]] = []

    async def begin(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft | None:
        self.begins.append((wa_jid, employee_id, attendance_key))
        return self.begin_result

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared += 1


class _ContextStore:
    def __init__(self) -> None:
        self.cleared = 0

    async def clear(self, wa_jid: str) -> None:
        assert wa_jid == _JID
        self.cleared += 1


class _Router:
    def __init__(self, result: AttendanceReminderRouteResult) -> None:
        self.result = result
        self.calls = 0

    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        assert context.employee_id == _EMPLOYEE_ID
        assert context.cycle_id == _CYCLE_ID
        assert context.attendance_keys == (_FIRST_KEY, _NEXT_KEY)
        assert employee_id == _EMPLOYEE_ID
        assert now == _NOW
        self.calls += 1
        return self.result


def test_ready_draft_renders_explicit_review_actions() -> None:
    rendered = render_payroll_draft_prompt(_draft())

    assert "Ajukan informasi ini?" in rendered
    assert PAYROLL_DRAFT_SUBMIT_ACTION_ID in rendered
    assert PAYROLL_DRAFT_EDIT_ACTION_ID in rendered
    assert "Clock Out: 17:40" in rendered
    assert "Bukti: ✓" in rendered


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ajukan", PayrollDraftCommand.SUBMIT),
        ("1", PayrollDraftCommand.SUBMIT),
        ("ubah", PayrollDraftCommand.EDIT),
        ("2", PayrollDraftCommand.EDIT),
    ],
)
def test_review_command_has_text_and_numeric_fallback(
    text: str,
    expected: PayrollDraftCommand,
) -> None:
    assert parse_payroll_draft_command(text) is expected


@pytest.mark.asyncio
async def test_submit_uses_durable_draft_then_opens_next_snapshot_gap() -> None:
    resolutions = _ResolutionService(SubmitOutcome.CREATED)
    next_draft = _draft(_NEXT_KEY, proposal=False, evidence=False)
    state = _State(next_draft)
    context_store = _ContextStore()
    router = _Router(
        AttendanceReminderRouteResult(
            AttendanceReminderRouteStatus.OPEN,
            _next_selection(),
        )
    )

    response = await submit_payroll_attendance_draft(
        jid=_JID,
        draft=_draft(),
        context=_context(),
        now=_NOW,
        resolutions=resolutions,
        state=state,
        context_store=context_store,
        routing=router,
    )

    assert resolutions.calls == [
        (_EMPLOYEE_ID, _FIRST_KEY, _JID, ResolutionType.MISSING_CLOCK_OUT, time(17, 40))
    ]
    assert state.cleared == 1
    assert state.begins == [(_JID, _EMPLOYEE_ID, _NEXT_KEY)]
    assert context_store.cleared == 0
    assert "sudah diajukan ke PMO" in response
    assert "Selanjutnya" in response
    assert "Jam pulang berapa?" in response
    assert "Mobile" not in response
    assert "Menu" not in response


@pytest.mark.asyncio
async def test_submit_final_gap_clears_context_and_only_claims_waiting_review() -> None:
    state = _State()
    context_store = _ContextStore()
    router = _Router(AttendanceReminderRouteResult(AttendanceReminderRouteStatus.NO_ACTION))

    response = await submit_payroll_attendance_draft(
        jid=_JID,
        draft=_draft(),
        context=_context(),
        now=_NOW,
        resolutions=_ResolutionService(SubmitOutcome.CREATED),
        state=state,
        context_store=context_store,
        routing=router,
    )

    assert state.cleared == 1
    assert context_store.cleared == 1
    assert "Tidak ada action Talent lain" in response
    assert "menunggu review PMO" in response
    assert "payroll-ready" not in response.casefold()


@pytest.mark.asyncio
async def test_source_change_does_not_claim_a_request_was_submitted() -> None:
    state = _State()
    context_store = _ContextStore()
    router = _Router(AttendanceReminderRouteResult(AttendanceReminderRouteStatus.NO_ACTION))

    response = await submit_payroll_attendance_draft(
        jid=_JID,
        draft=_draft(),
        context=_context(),
        now=_NOW,
        resolutions=_ResolutionService(SubmitOutcome.SOURCE_NOT_ELIGIBLE),
        state=state,
        context_store=context_store,
        routing=router,
    )

    assert state.cleared == 1
    assert context_store.cleared == 1
    assert "informasi lama tidak diajukan" in response
    assert "menunggu review PMO" not in response
    assert "Tidak ada action Talent lain" in response


@pytest.mark.asyncio
async def test_missing_evidence_keeps_draft_open_for_reupload() -> None:
    state = _State()
    context_store = _ContextStore()
    router = _Router(AttendanceReminderRouteResult(AttendanceReminderRouteStatus.NO_ACTION))

    response = await submit_payroll_attendance_draft(
        jid=_JID,
        draft=_draft(),
        context=_context(),
        now=_NOW,
        resolutions=_ResolutionService(SubmitOutcome.EVIDENCE_REQUIRED),
        state=state,
        context_store=context_store,
        routing=router,
    )

    assert state.cleared == 0
    assert context_store.cleared == 0
    assert router.calls == 0
    assert "Kirim ulang screenshot/dokumen" in response


@pytest.mark.asyncio
async def test_edit_reopens_same_gap_and_keeps_existing_evidence_fact() -> None:
    reset = _draft(proposal=False, evidence=True)
    state = _State(reset)

    response = await edit_payroll_attendance_draft(
        jid=_JID,
        draft=_draft(),
        state=state,
    )

    assert state.begins == [(_JID, _EMPLOYEE_ID, _FIRST_KEY)]
    assert state.cleared == 0
    assert "silakan ubah" in response
    assert "Bukti sudah ada" in response
    assert "Jam pulang berapa?" in response
