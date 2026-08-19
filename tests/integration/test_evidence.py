import os
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from digital_bast.bot.evidence import (
    EvidenceCandidate,
    EvidenceService,
    UploadOutcome,
    outstanding,
    select_by_index,
)
from digital_bast.domain.identity import task_key
from digital_bast.domain.models import EmployeeId, RecordOrigin, Task, TaskCategory, TaskSource
from digital_bast.infrastructure.repositories import PostgresDomainRepository

_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
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
    environment = pytest.MonkeyPatch()
    environment.setenv("APP_DATABASE_DSN", dsn)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield dsn
    finally:
        environment.undo()


def _make_task(employee_id: str, title: str, status: str, work_date: date) -> Task:
    source_id = uuid4().hex
    return Task(
        key=task_key(work_date, EmployeeId(employee_id), title, TaskSource.REDMINE, source_id),
        employee_id=EmployeeId(employee_id),
        work_date=work_date,
        title=title,
        requestor="Requestor",
        status=status,
        category=TaskCategory.CODE_QUALITY,
        source=TaskSource.REDMINE,
        source_id=source_id,
        assignee=None,
        start_at=None,
        response_at=None,
        close_at=None,
        end_date=None,
        achievement=100,
        origin=RecordOrigin.PIPELINE,
    )


@pytest.mark.asyncio
async def test_only_closed_tasks_are_candidates(database_dsn: str) -> None:
    repository = PostgresDomainRepository(database_dsn)
    employee_id = f"MTG-TF/TEST{uuid4().hex[:8]}"
    work_date = date(2026, 8, 12)
    closed = _make_task(employee_id, "CCTV Gate 2", "Closed", work_date)
    open_task = _make_task(employee_id, "Firmware Validation", "In Progress", work_date)
    await repository.upsert(closed)
    await repository.upsert(open_task)

    service = EvidenceService(database_dsn)
    candidates = await service.list_candidates(employee_id)

    assert [candidate.title for candidate in candidates] == ["CCTV Gate 2"]
    assert outstanding(candidates) == candidates


@pytest.mark.asyncio
async def test_upload_rejects_not_owned_and_not_closed(database_dsn: str) -> None:
    repository = PostgresDomainRepository(database_dsn)
    owner = f"MTG-TF/TEST{uuid4().hex[:8]}"
    other = f"MTG-TF/TEST{uuid4().hex[:8]}"
    work_date = date(2026, 8, 12)
    closed = _make_task(owner, "CCTV Gate 2", "Closed", work_date)
    open_task = _make_task(owner, "Firmware Validation", "In Progress", work_date)
    await repository.upsert(closed)
    await repository.upsert(open_task)

    service = EvidenceService(database_dsn)

    not_owned = await service.upload(other, "domain", str(closed.key), _PNG_1X1, "")
    not_closed = await service.upload(owner, "domain", str(open_task.key), _PNG_1X1, "")

    assert not_owned.outcome is UploadOutcome.NOT_OWNED
    assert not_closed.outcome is UploadOutcome.NOT_CLOSED


@pytest.mark.asyncio
async def test_upload_stores_once_and_dedupes_by_hash(database_dsn: str) -> None:
    repository = PostgresDomainRepository(database_dsn)
    employee_id = f"MTG-TF/TEST{uuid4().hex[:8]}"
    work_date = date(2026, 8, 12)
    task = _make_task(employee_id, "CCTV Gate 2", "Closed", work_date)
    await repository.upsert(task)

    service = EvidenceService(database_dsn)
    first = await service.upload(employee_id, "domain", str(task.key), _PNG_1X1, "cctv")
    second = await service.upload(employee_id, "domain", str(task.key), _PNG_1X1, "cctv again")

    assert first.outcome is UploadOutcome.STORED
    assert second.outcome is UploadOutcome.DUPLICATE

    remaining = outstanding(await service.list_candidates(employee_id))
    assert remaining == ()


def test_select_by_index_is_1_based_and_bounded() -> None:
    candidates = (
        EvidenceCandidate("domain", "a", "A", date(2026, 8, 1), 0),
        EvidenceCandidate("domain", "b", "B", date(2026, 8, 1), 0),
    )

    assert select_by_index(candidates, "1") is candidates[0]
    assert select_by_index(candidates, "2") is candidates[1]
    assert select_by_index(candidates, "0") is None
    assert select_by_index(candidates, "3") is None
    assert select_by_index(candidates, "abc") is None
