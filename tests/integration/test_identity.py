import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from digital_bast.bot.identity import ActivationOutcome, ActivationService
from digital_bast.cli import bot_reply


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
    environment = pytest.MonkeyPatch()
    environment.setenv("APP_DATABASE_DSN", dsn)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield dsn
    finally:
        environment.undo()


@pytest.fixture
def employee_id() -> str:
    return f"MTG-TF/TEST{uuid4().hex[:8]}"


@pytest.fixture
def jid() -> str:
    return f"62{uuid4().hex[:10]}@s.whatsapp.net"


@pytest.mark.asyncio
async def test_activation_binds_once(database_dsn: str, employee_id: str, jid: str) -> None:
    service = ActivationService(database_dsn)
    codes = await service.issue_codes((employee_id,))

    assert await service.resolve(jid) is None

    result = await service.activate(jid, employee_id, codes[employee_id])

    assert result.outcome is ActivationOutcome.SUCCESS
    assert await service.resolve(jid) == employee_id


@pytest.mark.asyncio
async def test_wrong_code_counts_a_failure_but_correct_code_still_works(
    database_dsn: str, employee_id: str, jid: str
) -> None:
    service = ActivationService(database_dsn)
    codes = await service.issue_codes((employee_id,))

    wrong = await service.activate(jid, employee_id, "WRONGCODE")
    right = await service.activate(jid, employee_id, codes[employee_id])

    assert wrong.outcome is ActivationOutcome.INVALID_CODE
    assert right.outcome is ActivationOutcome.SUCCESS


@pytest.mark.asyncio
async def test_five_failed_attempts_lock_the_employee(
    database_dsn: str, employee_id: str, jid: str
) -> None:
    service = ActivationService(database_dsn)
    codes = await service.issue_codes((employee_id,))

    outcomes = [
        (await service.activate(jid, employee_id, "WRONGCODE")).outcome for _ in range(5)
    ]

    assert outcomes[:4] == [ActivationOutcome.INVALID_CODE] * 4
    assert outcomes[4] is ActivationOutcome.LOCKED

    still_locked = await service.activate(jid, employee_id, codes[employee_id])
    assert still_locked.outcome is ActivationOutcome.LOCKED


@pytest.mark.asyncio
async def test_code_expires_after_first_successful_use(
    database_dsn: str, employee_id: str, jid: str
) -> None:
    service = ActivationService(database_dsn)
    codes = await service.issue_codes((employee_id,))
    _ = await service.activate(jid, employee_id, codes[employee_id])

    other_jid = f"62{uuid4().hex[:10]}@s.whatsapp.net"
    replay = await service.activate(other_jid, employee_id, codes[employee_id])

    assert replay.outcome is ActivationOutcome.ALREADY_USED


@pytest.mark.asyncio
async def test_unknown_employee_id_is_rejected(database_dsn: str, jid: str) -> None:
    service = ActivationService(database_dsn)

    result = await service.activate(jid, "MTG-TF/DOES-NOT-EXIST", "ANYCODE1")

    assert result.outcome is ActivationOutcome.UNKNOWN_EMPLOYEE


def test_unbound_dm_jid_can_only_attempt_activation(database_dsn: str, jid: str) -> None:
    reply = bot_reply("evidence", jid=jid, channel="dm")

    assert "aktivasi" in reply.casefold()
    assert "belum terhubung" in reply.casefold()
