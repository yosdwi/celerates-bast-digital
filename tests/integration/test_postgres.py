import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from digital_bast.application.ports import SyncCursor
from digital_bast.domain.errors import CursorRegressionError
from digital_bast.domain.models import EntityKind, Holiday, Month, RecordKey, RecordOrigin
from digital_bast.infrastructure.postgres import PostgresStore
from digital_bast.infrastructure.repositories import PostgresCursorStore, PostgresDomainRepository
from digital_bast.web.contracts import EmployeeOption, GenerationPlanInput, SectionInput
from digital_bast.web.postgres_backend import PostgresWebBackend


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


@pytest.mark.asyncio
async def test_upsert_and_month_listing_round_trip(database_dsn: str) -> None:
    repository = PostgresDomainRepository(database_dsn)
    suffix = uuid4().hex
    record = Holiday(
        key=RecordKey(f"holiday:2026-08-17:{suffix}"),
        work_date=date(2026, 8, 17),
        name="Independence Day",
        origin=RecordOrigin.PIPELINE,
    )

    await repository.upsert(record)
    loaded = await repository.get(record.key)
    month = await repository.list_month(EntityKind.HOLIDAY, Month(2026, 8))

    assert loaded == record
    assert record in month


@pytest.mark.asyncio
async def test_cursor_replay_cannot_move_watermark_backwards(database_dsn: str) -> None:
    store = PostgresCursorStore(database_dsn)
    source = f"source-{uuid4().hex}"
    current = datetime(2026, 8, 3, 12, tzinfo=UTC)
    await store.save(SyncCursor(source, "cursor-2", current))

    with pytest.raises(CursorRegressionError):
        await store.save(SyncCursor(source, "cursor-1", current - timedelta(minutes=1)))

    assert await store.load(source) == SyncCursor(source, "cursor-2", current)


def test_manual_lock_conflict_and_owner_release(database_dsn: str) -> None:
    store = PostgresStore(database_dsn)
    key = f"record-{uuid4().hex}"

    assert store.acquire_lock(key, "owner-a", 60)
    assert not store.acquire_lock(key, "owner-b", 60)
    assert not store.release_lock(key, "owner-b")
    assert store.release_lock(key, "owner-a")


@pytest.mark.asyncio
async def test_web_backend_reads_durable_data_and_generates_report(database_dsn: str) -> None:
    suffix = uuid4().hex
    task_id = f"task-{suffix}"
    attendance_id = f"attendance-{suffix}"
    with psycopg.connect(database_dsn) as connection:
        _ = connection.execute(
            """
            INSERT INTO durable_records (source, external_id, entity_kind, work_date, payload)
            VALUES
                ('test', %s, 'task', '2026-08-03', %s),
                ('test', %s, 'attendance', '2026-08-03', %s)
            """,
            (
                task_id,
                Jsonb(
                    {
                        "achievement": 100,
                        "category": "Detail Aktivitas Kualitas Kode",
                        "employee_id": suffix,
                        "full_name": "Owner Test",
                        "role": "Developer",
                        "status": "Closed",
                        "title": "Release verification",
                    }
                ),
                attendance_id,
                Jsonb(
                    {
                        "check_in": "08:00",
                        "check_out": "17:00",
                        "employee_id": suffix,
                        "full_name": "Owner Test",
                        "role": "Developer",
                        "shift": "Regular",
                    }
                ),
            ),
        )
    backend = PostgresWebBackend(database_dsn)

    report = await backend.report("developer", 2026, 8, evidence_only=True)
    employees = await backend.employees()
    attendance = await backend.attendance(("Owner Test",), date(2026, 8, 3), date(2026, 8, 3))
    plan = await backend.create_plan(GenerationPlanInput(type="developer", month=8, year=2026))
    section = await backend.generate_section(SectionInput(plan_id=plan.plan_id, section_id=0))
    bulk = await backend.bulk_data(plan.plan_id)

    assert await backend.ready()
    assert any(item.label == "Release verification" for item in report.items)
    assert EmployeeOption(name="Owner Test", role="Developer") in employees
    assert any(row.employee_id == suffix for row in attendance)
    assert plan.success
    assert section.success
    assert "Release verification" in bulk.content
