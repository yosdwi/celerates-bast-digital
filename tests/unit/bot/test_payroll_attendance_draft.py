from datetime import date, time

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.bot.attendance_resolution_dm_state import AttendanceResolutionDraft
from digital_bast.bot.payroll_attendance_draft import (
    PAYROLL_DRAFT_EDIT_ACTION_ID,
    PAYROLL_DRAFT_SUBMIT_ACTION_ID,
    PayrollDraftCommand,
    PayrollPresenceCommand,
    parse_payroll_draft_command,
    parse_payroll_presence_command,
    render_payroll_draft_prompt,
    select_payroll_proposal,
)


def _draft(
    resolution_type: ResolutionType,
    *,
    has_evidence: bool = False,
    proposed_check_in: time | None = None,
    proposed_check_out: time | None = None,
    absence_type: AbsenceType | None = None,
) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key="ATT-2026-09-04",
        employee_id="MTG-TF/TEST1",
        resolution_type=resolution_type,
        work_date=date(2026, 9, 4),
        proposed_check_in=proposed_check_in,
        proposed_check_out=proposed_check_out,
        absence_type=absence_type,
        has_evidence=has_evidence,
    )


def test_presence_command_recognizes_the_prompt_s_own_numbered_label() -> None:
    """Regression: the presence prompt itself renders "1. Masuk kerja\n2.
    Tidak masuk" with digit-shortcut replies remembered client-side, but
    that client-side translation only fires for a bare digit and can get
    clobbered by a crossed-over prompt (confirmed live: a real Talent's
    "1. Masuk kerja" reply fell through as an unrecognized presence answer
    and got misread by the natural-language date parser instead, jumping
    to a different day's gap). The parser must recognize its own numbered
    label directly, not only a bare digit or the bare word.
    """
    assert parse_payroll_presence_command("1. Masuk kerja") is PayrollPresenceCommand.WORKED
    assert parse_payroll_presence_command("2. Tidak masuk") is PayrollPresenceCommand.ABSENT
    assert parse_payroll_presence_command("1") is PayrollPresenceCommand.WORKED
    assert parse_payroll_presence_command("2") is PayrollPresenceCommand.ABSENT
    assert parse_payroll_presence_command("masuk kerja") is PayrollPresenceCommand.WORKED
    assert parse_payroll_presence_command("tidak masuk") is PayrollPresenceCommand.ABSENT
    assert parse_payroll_presence_command("3. Masuk kerja") is None
    assert parse_payroll_presence_command("") is None


def test_draft_command_recognizes_its_own_numbered_label() -> None:
    assert parse_payroll_draft_command("1. Ajukan") is PayrollDraftCommand.SUBMIT
    assert parse_payroll_draft_command("2. Ubah") is PayrollDraftCommand.EDIT
    assert parse_payroll_draft_command("1") is PayrollDraftCommand.SUBMIT
    assert parse_payroll_draft_command("2") is PayrollDraftCommand.EDIT


def test_single_clock_is_selected_for_the_actual_missing_clock_out() -> None:
    proposal = select_payroll_proposal(
        _draft(ResolutionType.MISSING_CLOCK_OUT),
        "17.40",
    )

    assert proposal is not None
    assert proposal.resolution_type is ResolutionType.MISSING_CLOCK_OUT
    assert proposal.proposed_check_out == time(17, 40)
    assert proposal.proposed_check_in is None


def test_single_clock_is_not_enough_for_a_both_missing_day() -> None:
    proposal = select_payroll_proposal(
        _draft(ResolutionType.MISSING_BOTH_WORKED),
        "07.30",
    )

    assert proposal is None


def test_both_missing_day_accepts_explicit_absence() -> None:
    proposal = select_payroll_proposal(
        _draft(ResolutionType.MISSING_BOTH_WORKED),
        "sakit",
    )

    assert proposal is not None
    assert proposal.resolution_type is ResolutionType.ABSENCE
    assert proposal.absence_type is AbsenceType.SAKIT


def test_saved_clock_without_evidence_asks_only_for_evidence() -> None:
    text = render_payroll_draft_prompt(
        _draft(
            ResolutionType.MISSING_CLOCK_OUT,
            proposed_check_out=time(17, 40),
        ),
        prefix="Oke, informasi attendance sudah tersimpan.",
    )

    assert "4 September" in text
    assert "Clock Out: 17:40" in text
    assert "kirim screenshot/bukti attendance" in text
    assert "PMO" not in text


def test_saved_clock_with_existing_evidence_moves_to_explicit_review() -> None:
    text = render_payroll_draft_prompt(
        _draft(
            ResolutionType.MISSING_CLOCK_OUT,
            proposed_check_out=time(17, 40),
            has_evidence=True,
        )
    )

    assert "Clock Out: 17:40" in text
    assert "Bukti: ✓" in text
    assert "Ajukan informasi ini?" in text
    assert PAYROLL_DRAFT_SUBMIT_ACTION_ID in text
    assert PAYROLL_DRAFT_EDIT_ACTION_ID in text
    assert "Menunggu approval" not in text
