import csv
import io
import os
from datetime import date, time
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from digital_bast.bot.attendance_resolution import (
    AbsenceType,
    AttendanceResolutionService,
    DecisionOutcome,
    ResolutionStatus,
    ResolutionType,
    SubmitOutcome,
)
from digital_bast.web.postgres_backend import PostgresWebBackend


@pytest.fixture(scope="module")
def database_dsn() -> str:
    dsn = os.getenv("TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("TEST_DATABASE_DSN is not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.OperationalError as error:
        pytest.skip(f"TEST_DATABASE_DSN is unavailable: {error.sqlstate or 'connection failed'}")
    command.upgrade(Config("alembic.ini"), "head")
    return dsn


def seed_attendance(  # noqa: PLR0913
    dsn: str,
    *,
    check_in: time | None,
    check_out: time | None,
    role: str = "Developer",
    work_date: date = date(2026, 8, 28),
    schedule_in: str = "",
    schedule_out: str = "",
) -> tuple[str, str, str, str]:
    suffix = uuid4().hex[:10]
    employee_id = f"MTG-TF/RES-{suffix}"
    nrp = f"RES{suffix}"
    full_name = f"Resolution Test {suffix}"
    attendance_key = f"ATT-{suffix}"
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO employees (employee_id, nrp, full_name, role)
            VALUES (%s, %s, %s, %s)
            """,
            (employee_id, nrp, full_name, role),
        )
        cursor.execute(
            """
            INSERT INTO attendance (
                record_key, employee_id, work_date, schedule_in, schedule_out,
                check_in, check_out
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                attendance_key,
                employee_id,
                work_date,
                schedule_in,
                schedule_out,
                check_in,
                check_out,
            ),
        )
        attendance_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO attendance_evidence (
                attendance_id, employee_id, work_date, caption,
                content_type, byte_size, sha256, image
            ) VALUES (%s, %s, %s, 'approval screenshot',
                      'image/jpeg', 3, %s, %s)
            """,
            (
                attendance_id,
                employee_id,
                work_date,
                uuid4().hex,
                b"abc",
            ),
        )
    return employee_id, nrp, full_name, attendance_key


def parse_legacy_csv(content: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content), delimiter=";"))


@pytest.mark.asyncio
async def test_approved_missing_clock_out_never_mutates_client_attendance(
    database_dsn: str,
) -> None:
    employee_id, _, _, attendance_key = seed_attendance(
        database_dsn, check_in=time(8, 3), check_out=None
    )
    service = AttendanceResolutionService(database_dsn)

    submitted = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.MISSING_CLOCK_OUT,
        proposed_check_out=time(17, 23),
    )
    assert submitted.outcome is SubmitOutcome.CREATED
    assert submitted.request_id is not None

    decided = await service.decide(
        submitted.request_id,
        "pmo@example.com",
        approve=True,
    )
    assert decided == type(decided)(DecisionOutcome.UPDATED, ResolutionStatus.APPROVED)

    with psycopg.connect(database_dsn) as connection:
        row = connection.execute(
            "SELECT check_in, check_out FROM attendance WHERE record_key = %s",
            (attendance_key,),
        ).fetchone()
    assert row == (time(8, 3), None)


@pytest.mark.asyncio
async def test_complete_source_attendance_cannot_enter_resolution_workflow(
    database_dsn: str,
) -> None:
    employee_id, _, _, attendance_key = seed_attendance(
        database_dsn, check_in=time(8, 0), check_out=time(17, 0)
    )
    service = AttendanceResolutionService(database_dsn)

    result = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.MISSING_CLOCK_OUT,
        proposed_check_out=time(17, 23),
    )

    assert result.outcome is SubmitOutcome.SOURCE_NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_absence_requires_both_source_punches_empty(database_dsn: str) -> None:
    employee_id, _, _, attendance_key = seed_attendance(
        database_dsn, check_in=None, check_out=None
    )
    service = AttendanceResolutionService(database_dsn)

    result = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.ABSENCE,
        absence_type=AbsenceType.SAKIT,
    )

    assert result.outcome is SubmitOutcome.CREATED


@pytest.mark.asyncio
async def test_libur_absence_can_be_submitted_and_approved(database_dsn: str) -> None:
    employee_id, _, _, attendance_key = seed_attendance(
        database_dsn, check_in=None, check_out=None
    )
    service = AttendanceResolutionService(database_dsn)

    submitted = await service.submit(
        employee_id,
        attendance_key,
        "pmo-web:pmo@example.com",
        ResolutionType.ABSENCE,
        absence_type=AbsenceType.LIBUR,
    )
    assert submitted.outcome is SubmitOutcome.CREATED
    assert submitted.request_id is not None

    decided = await service.decide(submitted.request_id, "pmo@example.com", approve=True)
    assert decided.outcome is DecisionOutcome.UPDATED
    assert decided.status is ResolutionStatus.APPROVED


@pytest.mark.asyncio
async def test_reject_requires_reason_and_decision_is_idempotent(database_dsn: str) -> None:
    employee_id, _, _, attendance_key = seed_attendance(
        database_dsn, check_in=None, check_out=time(17, 12)
    )
    service = AttendanceResolutionService(database_dsn)
    submitted = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.MISSING_CLOCK_IN,
        proposed_check_in=time(7, 41),
    )
    assert submitted.request_id is not None

    no_reason = await service.decide(submitted.request_id, "pmo@example.com", approve=False)
    assert no_reason.outcome is DecisionOutcome.REJECTION_REASON_REQUIRED

    rejected = await service.decide(
        submitted.request_id,
        "pmo@example.com",
        approve=False,
        rejection_reason="Jam tidak dapat diverifikasi",
    )
    assert rejected.status is ResolutionStatus.REJECTED

    replay = await service.decide(
        submitted.request_id,
        "other-pmo@example.com",
        approve=True,
    )
    assert replay.outcome is DecisionOutcome.ALREADY_RESOLVED
    assert replay.status is ResolutionStatus.REJECTED


@pytest.mark.asyncio
async def test_csv_projects_actual_plus_approved_missing_clock_out(database_dsn: str) -> None:
    employee_id, _, full_name, attendance_key = seed_attendance(
        database_dsn, check_in=time(8, 3), check_out=None
    )
    service = AttendanceResolutionService(database_dsn)
    submitted = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.MISSING_CLOCK_OUT,
        proposed_check_out=time(17, 23),
    )
    assert submitted.request_id is not None
    await service.decide(submitted.request_id, "pmo@example.com", approve=True)

    content, rows = await PostgresWebBackend(database_dsn).attendance_legacy(
        "Developer", date(2026, 8, 28), date(2026, 8, 28), full_name
    )
    parsed = parse_legacy_csv(content)

    assert rows == 1
    assert parsed[1][9] == "08:03"
    assert parsed[1][10] == "17:23"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("work_date", "expected_out"),
    [(date(2026, 8, 27), "16:30"), (date(2026, 8, 28), "17:00")],
)
async def test_csv_projects_developer_absence_to_default_schedule(
    database_dsn: str, work_date: date, expected_out: str
) -> None:
    employee_id, _, full_name, attendance_key = seed_attendance(
        database_dsn,
        check_in=None,
        check_out=None,
        work_date=work_date,
    )
    service = AttendanceResolutionService(database_dsn)
    submitted = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.ABSENCE,
        absence_type=AbsenceType.IZIN,
    )
    assert submitted.request_id is not None
    await service.decide(submitted.request_id, "pmo@example.com", approve=True)

    content, rows = await PostgresWebBackend(database_dsn).attendance_legacy(
        "Developer", work_date, work_date, full_name
    )
    parsed = parse_legacy_csv(content)

    assert rows == 1
    assert parsed[1][9] == "07:30"
    assert parsed[1][10] == expected_out


@pytest.mark.asyncio
async def test_csv_projects_iot_absence_from_shift_schedule(database_dsn: str) -> None:
    work_date = date(2026, 8, 28)
    employee_id, _, full_name, attendance_key = seed_attendance(
        database_dsn,
        check_in=None,
        check_out=None,
        role="IoT Operations",
        work_date=work_date,
        schedule_in="19:00",
        schedule_out="07:00",
    )
    service = AttendanceResolutionService(database_dsn)
    submitted = await service.submit(
        employee_id,
        attendance_key,
        "628123@s.whatsapp.net",
        ResolutionType.ABSENCE,
        absence_type=AbsenceType.SAKIT,
    )
    assert submitted.request_id is not None
    await service.decide(submitted.request_id, "pmo@example.com", approve=True)

    content, rows = await PostgresWebBackend(database_dsn).attendance_legacy(
        "IoT Operations", work_date, work_date, full_name
    )
    parsed = parse_legacy_csv(content)

    assert rows == 1
    assert parsed[1][9] == "19:00"
    assert parsed[1][10] == "07:00"
