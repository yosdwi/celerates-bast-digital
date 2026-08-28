import os
from collections.abc import Iterator
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


@pytest.fixture(scope="module")
def database_dsn() -> Iterator[str]:
    dsn = os.getenv("TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("TEST_DATABASE_DSN is not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.OperationalError as error:
        pytest.skip(f"TEST_DATABASE_DSN is unavailable: {error.sqlstate or 'connection failed'}")
    command.upgrade(Config("alembic.ini"), "head")
    yield dsn


def seed_attendance(
    dsn: str,
    *,
    check_in: time | None,
    check_out: time | None,
) -> tuple[str, str, str]:
    suffix = uuid4().hex[:10]
    employee_id = f"MTG-TF/RES-{suffix}"
    nrp = f"RES{suffix}"
    attendance_key = f"ATT-{suffix}"
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO employees (employee_id, nrp, full_name, role)
            VALUES (%s, %s, %s, 'Developer')
            """,
            (employee_id, nrp, f"Resolution Test {suffix}"),
        )
        cursor.execute(
            """
            INSERT INTO attendance (
                record_key, employee_id, work_date, check_in, check_out
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (attendance_key, employee_id, date(2026, 8, 28), check_in, check_out),
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
                date(2026, 8, 28),
                uuid4().hex,
                b"abc",
            ),
        )
    return employee_id, nrp, attendance_key


@pytest.mark.asyncio
async def test_approved_missing_clock_out_never_mutates_client_attendance(database_dsn: str) -> None:
    employee_id, _, attendance_key = seed_attendance(
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
async def test_complete_source_attendance_cannot_enter_resolution_workflow(database_dsn: str) -> None:
    employee_id, _, attendance_key = seed_attendance(
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
    employee_id, _, attendance_key = seed_attendance(
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
async def test_reject_requires_reason_and_decision_is_idempotent(database_dsn: str) -> None:
    employee_id, _, attendance_key = seed_attendance(
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
