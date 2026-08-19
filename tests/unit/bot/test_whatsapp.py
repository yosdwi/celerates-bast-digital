from __future__ import annotations

from datetime import date

from digital_bast.bot.whatsapp import (
    HELP_REPLY,
    Intent,
    extract_index,
    format_completion,
    format_employee_detail,
    format_evidence_resume,
    format_system_status,
    parse_command,
    parse_period,
)
from digital_bast.domain.completion import (
    AttendanceFact,
    DateRange,
    EmployeeFacts,
    TaskFact,
    TimesheetFact,
    evaluate_completion,
)
from digital_bast.infrastructure.docker_status import ServiceStatus, SystemStatus

TODAY = date(2026, 8, 18)


def test_parses_indonesian_day_range_sharing_one_month() -> None:
    assert parse_period("status 1 sampai 31 Agustus", TODAY) == DateRange(
        date(2026, 8, 1), date(2026, 8, 31)
    )


def test_parses_two_month_range() -> None:
    assert parse_period("export attendance 20 Juli sampai 18 Agustus", TODAY) == DateRange(
        date(2026, 7, 20), date(2026, 8, 18)
    )


def test_parses_iso_range() -> None:
    assert parse_period("status 2026-08-01 sampai 2026-08-31", TODAY) == DateRange(
        date(2026, 8, 1), date(2026, 8, 31)
    )


def test_parses_whole_month_phrase() -> None:
    assert parse_period("status BAST Juli", TODAY) == DateRange(date(2026, 7, 1), date(2026, 7, 31))


def test_returns_none_without_dates() -> None:
    assert parse_period("status BAST", TODAY) is None


def test_intents_are_detected_from_mentions() -> None:
    assert parse_command("@BAST Bot status 1 sampai 31 Agustus", TODAY) == type(
        parse_command("status 1 sampai 31 Agustus", TODAY)
    )(Intent.COMPLETION_STATUS, DateRange(date(2026, 8, 1), date(2026, 8, 31)))
    assert parse_command("@BAST Bot system status", TODAY).intent is Intent.SYSTEM_STATUS
    assert (
        parse_command("@BAST Bot export attendance 20 Juli sampai 18 Agustus", TODAY).intent
        is Intent.EXPORT_ATTENDANCE
    )
    assert (
        parse_command("@BAST Bot generate BAST 1 sampai 31 Juli", TODAY).intent
        is Intent.GENERATE_BAST
    )


def test_container_mutation_is_rejected() -> None:
    assert parse_command("@BAST Bot restart postgres", TODAY).intent is Intent.UNSUPPORTED_MUTATION


def test_unknown_text_falls_back_to_help() -> None:
    assert parse_command("@BAST Bot xyzzy plugh qux", TODAY).intent is Intent.UNKNOWN
    assert HELP_REPLY.startswith("*@conform")


def test_greeting_is_conversation_not_unknown() -> None:
    # "halo" used to fall through to the generic HELP_REPLY -- it's now a
    # recognized conversation trigger (see _CONVERSATION_WORDS) so it gets a
    # persona reply instead.
    assert parse_command("@BAST Bot halo", TODAY).intent is Intent.CONVERSATION


def facts(name: str, *, closed: bool) -> EmployeeFacts:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 1))
    return EmployeeFacts(
        employee_id=name,
        name=name,
        off_days=frozenset(),
        attendance=(
            AttendanceFact(
                period.start, has_clock_in=True, has_clock_out=True, has_evidence=False
            ),
        ),
        timesheets=(TimesheetFact(period.start, "Shift Pagi"),),
        tasks=(TaskFact(period.start, "CCTV Gate 2", "Closed" if closed else "Open", 1),),
        evidence_available=True,
        attendance_available=True,
    )


def test_completion_message_is_compact_not_a_per_employee_dump() -> None:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 1))
    report = evaluate_completion(
        period, (facts("Titin", closed=True), facts("Putra", closed=False))
    )

    message = format_completion(report)

    assert message.startswith("*Status BAST — 1-1 Agustus 2026*")
    assert "Talent lengkap : 1/2" in message
    assert "1 talent masih perlu follow-up." in message
    # The old per-employee-per-issue dump must be gone from the group summary.
    assert "1. Titin" not in message
    assert "Putra" not in message
    assert "CCTV Gate 2" not in message


def test_evidence_resume_counts_only_real_not_closed_tasks() -> None:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 1))
    missing_evidence = EmployeeFacts(
        employee_id="1",
        name="Farhan",
        off_days=frozenset(),
        attendance=(),
        timesheets=(),
        tasks=(TaskFact(period.start, "CCTV Gate 2", "Closed", 0),),
        evidence_available=True,
        attendance_available=True,
    )
    not_closed = EmployeeFacts(
        employee_id="2",
        name="Hanung",
        off_days=frozenset(),
        attendance=(),
        timesheets=(),
        tasks=(TaskFact(period.start, "Firmware Validation", "In Progress", 0),),
        evidence_available=True,
        attendance_available=True,
    )
    no_tasks_at_all = EmployeeFacts(
        employee_id="3",
        name="Titin",
        off_days=frozenset(),
        attendance=(),
        timesheets=(),
        tasks=(),
        evidence_available=True,
        attendance_available=True,
    )

    report = evaluate_completion(period, (missing_evidence, not_closed, no_tasks_at_all))
    message = format_evidence_resume(report)

    assert "2/3 talent lengkap" in message
    assert "• Farhan — 1 Closed task tanpa evidence" in message
    assert "Task belum Closed: 1 (dari 2)" in message


def test_system_status_message_uses_friendly_labels() -> None:
    status = SystemStatus(
        overall="healthy",
        services=(
            ServiceStatus("postgres", "running", "healthy"),
            ServiceStatus("worker", "running", ""),
        ),
    )

    message = format_system_status(status)

    assert "✅ PostgreSQL — Healthy" in message
    assert "✅ Worker — Running" in message
    assert message.endswith("Overall: ✅ Sehat")


def test_employee_detail_groups_repeated_daily_issues_into_ranges() -> None:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 5))
    missing_days = EmployeeFacts(
        employee_id="Yoses",
        name="Yoses",
        off_days=frozenset(),
        attendance=(
            AttendanceFact(
                date(2026, 8, 4), has_clock_in=True, has_clock_out=True, has_evidence=False
            ),
        ),
        timesheets=(),
        tasks=(),
        evidence_available=True,
        attendance_available=True,
    )
    report = evaluate_completion(period, (missing_days,))

    message = format_employee_detail(report.employees[0], period)

    assert message.startswith("*Yoses — BAST 1-5 Agustus 2026*")
    # Days 1, 2, 3, 5 are missing attendance (4 is present) -- one grouped
    # line with a compressed range, not four separate per-date lines.
    assert "4 hari — Data attendance belum tersedia. (1-3, 5)" in message
    assert message.count(" — Data attendance belum tersedia.") == 1


def test_extract_index_handles_explicit_references() -> None:
    assert extract_index("1") == 1
    assert extract_index("buat poin 1") == 1
    assert extract_index("evidence task nomor 2") == 2
    assert extract_index("nomor satu") == 1
    assert extract_index("ini buat CCTV Gate") is None


def test_conversation_never_wins_over_a_business_keyword() -> None:
    # A business word anywhere in the message must route to the business
    # intent even when phrased casually/with a conversational word too --
    # conversation is checked last in _INTENT_RULES for exactly this reason.
    assert parse_command("@conform makasih ya udah export tadi", TODAY).intent is (
        Intent.EXPORT_ATTENDANCE
    )
    assert parse_command("@conform status bast agustus dong", TODAY).intent is (
        Intent.COMPLETION_STATUS
    )
    assert parse_command("@conform restart postgres dong", TODAY).intent is (
        Intent.UNSUPPORTED_MUTATION
    )


def test_persona_fallback_names_no_unshipped_capability() -> None:
    from digital_bast.bot.whatsapp import PERSONA_FALLBACK_REPLY  # noqa: PLC0415

    banned = ("approve", "restart", "edit redmine", "matikan", "hidupkan", "docker")
    lowered = PERSONA_FALLBACK_REPLY.casefold()
    assert not any(word in lowered for word in banned)
