"""Machine-to-machine ingest for bridge/pama_bridge.py.

The VPS cannot resolve either PAMA SQL Server host, so the PAMA Windows PC is
the only machine that can read attendance, Redmine, and the IoT sheet. It posts
raw source rows here over outbound HTTPS; every transform stays on this side so
the business rules live in one repository.

Idempotency comes from `ON CONFLICT (record_key)` in the repository, so an
overlapping lookback window can be re-sent freely -- that is what makes the
bridge safe to re-run after the PC was offline, a batch half-failed, or the
scheduler fired twice.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import date  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, ClassVar, Final

import holidays
import psycopg
from anyio.to_thread import run_sync
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from digital_bast.config import get_settings
from digital_bast.domain.identity import daily_key
from digital_bast.domain.transforms import transform_iot_task, transform_redmine_task
from digital_bast.infrastructure.json_types import JsonValue  # noqa: TC001
from digital_bast.infrastructure.pama_attendance import (
    bucket_punches,
    derive_day,
    parse_clock,
)
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.production_sources import parse_iot_sheet, parse_redmine_rows
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.infrastructure.source_sync_state import PostgresSourceSyncStateStore

if TYPE_CHECKING:
    from digital_bast.domain.models import DomainRecord, Employee

_LOGGER = logging.getLogger(__name__)
_MAX_ROWS: Final = 1000

router = APIRouter(prefix="/internal/sync", tags=["sync"], include_in_schema=False)


@dataclass(frozen=True, slots=True)
class _Window:
    """The arbitrary date range the bridge sends, satisfying `DateWindow`."""

    start: date
    end: date


class RosterEmployee(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    employee_id: str
    nrp: str
    full_name: str
    role: str


class RosterResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    employees: tuple[RosterEmployee, ...]


class AttendancePunch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    nrp: str = Field(min_length=1)
    att_date: date
    att_hour_label: str = ""


class AttendanceBatch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: list[AttendancePunch]


class RedmineBatch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    period_start: date
    period_end: date
    rows: list[dict[str, JsonValue]]


class IoTSheetBatch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    period_start: date
    period_end: date
    payload: dict[str, JsonValue]


class IngestResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    received: int
    upserted: int
    skipped_unmatched_nrp: int = 0
    unmatched_nrps: tuple[str, ...] = ()


def _authorize(authorization: str | None) -> None:
    expected = get_settings().sync_ingest_token
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingest is not configured",
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not secrets.compare_digest(
        token, expected.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid ingest credentials",
        )


def _guard_size(count: int) -> None:
    if count > _MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"batch exceeds {_MAX_ROWS} rows",
        )


def _dsn() -> str:
    dsn = get_settings().database_dsn
    if dsn is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="APP_DATABASE_DSN is not configured",
        )
    return dsn.get_secret_value()


async def _store(records: tuple[DomainRecord, ...], dsn: str) -> int:
    repository = PostgresDomainRepository(dsn)
    for record in records:
        await repository.upsert(record)
    return len(records)


async def _record_success(source_key: str, dsn: str) -> None:
    await PostgresSourceSyncStateStore(dsn).record_success(source_key)


@router.get("/roster", response_model=RosterResponse)
async def roster(
    authorization: Annotated[str | None, Header()] = None,
) -> RosterResponse:
    """The roster the bridge iterates over, so NRPs live in exactly one place."""
    _authorize(authorization)
    employees = await PostgresEmployeeSource(_dsn()).load()
    return RosterResponse(
        employees=tuple(
            RosterEmployee(
                employee_id=str(person.id),
                nrp=person.external_id,
                full_name=person.name,
                role=person.role.value,
            )
            for person in employees
        )
    )


@router.post("/attendance", response_model=IngestResult)
async def ingest_attendance(
    batch: AttendanceBatch,
    authorization: Annotated[str | None, Header()] = None,
) -> IngestResult:
    _authorize(authorization)
    _guard_size(len(batch.rows))
    dsn = _dsn()
    employees = await PostgresEmployeeSource(dsn).load()
    by_nrp = {person.external_id: person for person in employees}

    punches: dict[tuple[str, date], list[str]] = {}
    unmatched: set[str] = set()
    for row in batch.rows:
        if row.nrp not in by_nrp:
            unmatched.add(row.nrp)
            continue
        punches.setdefault((row.nrp, row.att_date), []).append(row.att_hour_label)

    upserted = await run_sync(_write_attendance, dsn, by_nrp, punches)
    _report_unmatched("attendance", unmatched)
    await _record_success("attendance", dsn)
    return IngestResult(
        received=len(batch.rows),
        upserted=upserted,
        skipped_unmatched_nrp=len(unmatched),
        unmatched_nrps=tuple(sorted(unmatched)),
    )


def _write_attendance(
    dsn: str,
    by_nrp: dict[str, Employee],
    punches: dict[tuple[str, date], list[str]],
) -> int:
    """Write one attendance bridge batch in a single transaction."""
    id_holidays: dict[date, str] = {}
    for year in sorted({work_date.year for _nrp, work_date in punches}):
        id_holidays.update(
            {day: str(name) for day, name in holidays.country_holidays("ID", years=year).items()}
        )
    written = 0
    with psycopg.connect(dsn, connect_timeout=5) as connection, connection.cursor() as cursor:
        for (nrp, work_date), labels in sorted(punches.items()):
            person = by_nrp[nrp]
            check_in, check_out = bucket_punches(labels)
            derived = derive_day(
                person.role,
                str(person.id),
                work_date,
                check_in,
                check_out,
                None,
                id_holidays,
            )
            _ = cursor.execute(
                """
                INSERT INTO attendance (
                    record_key, employee_id, work_date, shift, schedule_in,
                    schedule_out, attendance_code, check_in, check_out, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (record_key) DO UPDATE SET
                    shift = EXCLUDED.shift,
                    schedule_in = EXCLUDED.schedule_in,
                    schedule_out = EXCLUDED.schedule_out,
                    attendance_code = EXCLUDED.attendance_code,
                    check_in = EXCLUDED.check_in,
                    check_out = EXCLUDED.check_out,
                    notes = EXCLUDED.notes
                WHERE attendance.origin <> 'manual'
                """,
                (
                    str(daily_key("attendance", work_date, person.id)),
                    str(person.id),
                    work_date,
                    derived["shift"],
                    derived["schedule_in"],
                    derived["schedule_out"],
                    derived["attendance_code"],
                    parse_clock(check_in),
                    parse_clock(check_out),
                    derived["notes"],
                ),
            )
            written += 1
    return written


@router.post("/redmine", response_model=IngestResult)
async def ingest_redmine(
    batch: RedmineBatch,
    authorization: Annotated[str | None, Header()] = None,
) -> IngestResult:
    _authorize(authorization)
    _guard_size(len(batch.rows))
    dsn = _dsn()
    employees = await PostgresEmployeeSource(dsn).load()
    parsed = parse_redmine_rows(
        batch.rows,  # type: ignore[arg-type]
        employees,
        _Window(batch.period_start, batch.period_end),
    )
    records = tuple(transform_redmine_task(row) for row in parsed.rows)
    upserted = await _store(records, dsn)
    _report_unmatched("redmine", set(parsed.unmatched_nrps))
    await _record_success("redmine", dsn)
    return IngestResult(
        received=len(batch.rows),
        upserted=upserted,
        skipped_unmatched_nrp=len(parsed.unmatched_nrps),
        unmatched_nrps=parsed.unmatched_nrps,
    )


@router.post("/iot-sheet", response_model=IngestResult)
async def ingest_iot_sheet(
    batch: IoTSheetBatch,
    authorization: Annotated[str | None, Header()] = None,
) -> IngestResult:
    _authorize(authorization)
    dsn = _dsn()
    employees = await PostgresEmployeeSource(dsn).load()
    rows = parse_iot_sheet(batch.payload, _Window(batch.period_start, batch.period_end), employees)
    _guard_size(len(rows))
    records = tuple(transform_iot_task(row) for row in rows)
    upserted = await _store(records, dsn)
    await _record_success("iot_sheet", dsn)
    return IngestResult(received=len(rows), upserted=upserted)


def _report_unmatched(source: str, unmatched: set[str]) -> None:
    if unmatched:
        _LOGGER.warning(
            "%s ingest: %d NRPs matched no employee: %s",
            source,
            len(unmatched),
            ", ".join(sorted(unmatched)),
        )
