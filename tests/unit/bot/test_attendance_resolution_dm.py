from datetime import time

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.bot.attendance_resolution_dm import (
    looks_like_resolution_input,
    parse_clock_times,
    proposals,
)


def test_parse_clock_times_accepts_colon_and_dot() -> None:
    assert parse_clock_times("masuk 07:30 pulang 17.05") == (time(7, 30), time(17, 5))


def test_single_time_tries_missing_clock_in_then_clock_out() -> None:
    parsed = proposals("17:23")

    assert tuple(item.resolution_type for item in parsed) == (
        ResolutionType.MISSING_CLOCK_IN,
        ResolutionType.MISSING_CLOCK_OUT,
    )
    assert parsed[0].proposed_check_in == time(17, 23)
    assert parsed[1].proposed_check_out == time(17, 23)


def test_two_times_try_worked_day_then_single_gap_fallbacks() -> None:
    parsed = proposals("kerja 07:30 17:00")

    assert tuple(item.resolution_type for item in parsed) == (
        ResolutionType.MISSING_BOTH_WORKED,
        ResolutionType.MISSING_CLOCK_IN,
        ResolutionType.MISSING_CLOCK_OUT,
    )
    assert parsed[0].proposed_check_in == time(7, 30)
    assert parsed[0].proposed_check_out == time(17, 0)


def test_absence_is_explicit_and_has_no_clock_proposal() -> None:
    parsed = proposals("sakit")

    assert len(parsed) == 1
    assert parsed[0].resolution_type is ResolutionType.ABSENCE
    assert parsed[0].absence_type is AbsenceType.SAKIT
    assert parsed[0].proposed_check_in is None
    assert parsed[0].proposed_check_out is None


def test_mixed_absence_and_clock_is_ambiguous_instead_of_guessed() -> None:
    assert proposals("izin tapi jam 08:00") == ()


def test_work_word_without_time_keeps_user_in_resolution_flow() -> None:
    assert looks_like_resolution_input("aku kerja") is True
    assert proposals("aku kerja") == ()


def test_unrelated_greeting_is_not_intercepted() -> None:
    assert looks_like_resolution_input("halo conform") is False
