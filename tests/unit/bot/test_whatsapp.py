from __future__ import annotations

from datetime import date

from digital_bast.bot.whatsapp import (
    HELP_REPLY,
    Intent,
    format_completion,
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
    assert parse_command("@BAST Bot halo", TODAY).intent is Intent.UNKNOWN
    assert HELP_REPLY.startswith("*BAST Bot*")


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
        tasks=(TaskFact(period.start, "CCTV Gate 2", "Closed" if closed else "Open"),),
        task_evidence_count=1,
        attendance_available=True,
    )


def test_completion_message_lists_employees_and_follow_up() -> None:
    period = DateRange(date(2026, 8, 1), date(2026, 8, 1))
    report = evaluate_completion(
        period, (facts("Titin", closed=True), facts("Putra", closed=False))
    )

    message = format_completion(report)

    assert message.startswith("*Status BAST — 1-1 Agustus 2026*")
    assert "1. Titin" in message
    assert "*Perlu ditindaklanjuti*" in message
    assert '• Putra — Task "CCTV Gate 2" belum Closed.' in message


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
