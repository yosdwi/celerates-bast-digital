from __future__ import annotations

from datetime import UTC, date, datetime, time

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.bot.payroll_attendance_natural import (
    PayrollAttendanceCandidate,
    PayrollAttendanceNaturalInterpreter,
    explicit_work_date,
    explicit_work_date_for_period,
    proposal_for_active_gap,
)

_MESSAGE_AT = datetime(2026, 9, 8, 1, 30, tzinfo=UTC)  # 08:30 Asia/Jakarta
_ACTIVE_DATE = date(2026, 9, 7)


class _Client:
    def __init__(self, response: str | None) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str | None:
        self.calls.append((system, user))
        return self.response


def test_explicit_work_date_anchors_kemarin_to_message_timestamp() -> None:
    result = explicit_work_date(
        "jam pulang kemarin 17.40",
        message_at=_MESSAGE_AT,
        active_work_date=_ACTIVE_DATE,
    )

    assert result.mentioned is True
    assert result.work_date == _ACTIVE_DATE


def test_explicit_work_date_day_only_uses_active_gap_month_for_comparison() -> None:
    result = explicit_work_date(
        "tanggal 7 masuk 07.28",
        message_at=_MESSAGE_AT,
        active_work_date=_ACTIVE_DATE,
    )

    assert result.mentioned is True
    assert result.work_date == _ACTIVE_DATE


def test_conflicting_date_references_fail_closed() -> None:
    result = explicit_work_date(
        "kemarin tanggal 8 jam pulang 17.40",
        message_at=_MESSAGE_AT,
        active_work_date=_ACTIVE_DATE,
    )

    assert result.mentioned is True
    assert result.work_date is None


def test_cycle_date_parser_resolves_day_only_inside_21_to_20_cycle() -> None:
    result = explicit_work_date_for_period(
        "aku tanggal 1 itu cuti",
        message_at=datetime(2026, 9, 21, 8, 0, tzinfo=UTC),
        period_start=date(2026, 8, 21),
        period_end=date(2026, 9, 20),
    )

    assert result.mentioned is True
    assert result.work_date == date(2026, 9, 1)


def test_cycle_date_parser_resolves_month_name_across_previous_month() -> None:
    result = explicit_work_date_for_period(
        "22 Agustus saya sakit",
        message_at=datetime(2026, 9, 21, 8, 0, tzinfo=UTC),
        period_start=date(2026, 8, 21),
        period_end=date(2026, 9, 20),
    )

    assert result.mentioned is True
    assert result.work_date == date(2026, 8, 22)


def test_cycle_date_parser_fails_closed_for_conflicting_dates() -> None:
    result = explicit_work_date_for_period(
        "1 September cuti, bukan 15 September",
        message_at=datetime(2026, 9, 21, 8, 0, tzinfo=UTC),
        period_start=date(2026, 8, 21),
        period_end=date(2026, 9, 20),
    )

    assert result.mentioned is True
    assert result.work_date is None


async def test_interpreter_uses_message_timestamp_and_returns_typed_candidate() -> None:
    client = _Client(
        '{"work_date":"2026-09-07","resolution_type":"missing_clock_out",'
        '"check_in":null,"check_out":"17:40","absence_type":null}'
    )
    interpreter = PayrollAttendanceNaturalInterpreter(client)

    candidate = await interpreter.interpret(
        "kemarin pulangnya jam lima lewat empat puluh",
        message_at=_MESSAGE_AT,
        active_work_date=_ACTIVE_DATE,
        active_resolution_type=ResolutionType.MISSING_CLOCK_OUT,
    )

    assert candidate == PayrollAttendanceCandidate(
        work_date=_ACTIVE_DATE,
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        proposed_check_out=time(17, 40),
    )
    assert "2026-09-08T08:30:00+07:00" in client.calls[0][1]
    assert "2026-09-07" in client.calls[0][1]


def test_candidate_wrong_date_is_not_applicable_to_active_gap() -> None:
    candidate = PayrollAttendanceCandidate(
        work_date=date(2026, 9, 6),
        resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        proposed_check_out=time(17, 40),
    )

    assert (
        proposal_for_active_gap(
            candidate,
            active_work_date=_ACTIVE_DATE,
            active_resolution_type=ResolutionType.MISSING_CLOCK_OUT,
        )
        is None
    )


def test_missing_both_does_not_accept_single_clock_candidate() -> None:
    candidate = PayrollAttendanceCandidate(
        work_date=_ACTIVE_DATE,
        resolution_type=ResolutionType.MISSING_CLOCK_IN,
        proposed_check_in=time(7, 28),
    )

    assert (
        proposal_for_active_gap(
            candidate,
            active_work_date=_ACTIVE_DATE,
            active_resolution_type=ResolutionType.MISSING_BOTH_WORKED,
        )
        is None
    )


def test_missing_both_can_accept_explicit_absence_without_guessing_clocks() -> None:
    candidate = PayrollAttendanceCandidate(
        work_date=_ACTIVE_DATE,
        resolution_type=ResolutionType.ABSENCE,
        absence_type=AbsenceType.SAKIT,
    )

    proposal = proposal_for_active_gap(
        candidate,
        active_work_date=_ACTIVE_DATE,
        active_resolution_type=ResolutionType.MISSING_BOTH_WORKED,
    )

    assert proposal is not None
    assert proposal.resolution_type is ResolutionType.ABSENCE
    assert proposal.absence_type is AbsenceType.SAKIT
