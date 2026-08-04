from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, final

import psycopg
from anyio.to_thread import run_sync
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from digital_bast.domain.identity import canonical_text
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.domain.time import JAKARTA
from digital_bast.domain.transforms import IoTTaskInput

if TYPE_CHECKING:
    from collections.abc import Sequence

    from digital_bast.flows.models import Period
    from digital_bast.infrastructure.google import GooglePayload
    from digital_bast.infrastructure.nocodb import JsonValue, NocoDBClient


class _EmployeePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    record_id: str | int = Field(alias="Id")
    external_id: str = Field(alias="Employee ID")
    name: str = Field(alias="Employee Name")
    role: str = Field(alias="Role")
    status: str = Field(alias="Status")


class _ValueRange(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    values: list[list[str | int | float | bool | None]] = Field(default_factory=list)


class _BatchValues(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    value_ranges: list[_ValueRange] = Field(default_factory=list, alias="valueRanges")


class EmployeeSource(Protocol):
    async def load(self) -> tuple[Employee, ...]: ...


class SheetBatchReader(Protocol):
    def batch_get(self, spreadsheet_id: str, ranges: tuple[str, ...]) -> GooglePayload: ...


def parse_employees(records: Sequence[dict[str, JsonValue]]) -> tuple[Employee, ...]:
    employees: list[Employee] = []
    for record in records:
        try:
            payload = _EmployeePayload.model_validate(record)
            role = EmployeeRole(payload.role.strip())
        except (ValidationError, ValueError):
            continue
        if canonical_text(payload.status) != "active":
            continue
        employees.append(
            Employee(
                EmployeeId(str(payload.record_id)),
                payload.external_id.strip(),
                payload.name.strip(),
                role,
            )
        )
    return tuple(employees)


@final
class NocoDBEmployeeSource:
    def __init__(self, client: NocoDBClient, table_id: str) -> None:
        self._client = client
        self._table_id = table_id

    async def load(self) -> tuple[Employee, ...]:
        records = await run_sync(self._client.list_records, self._table_id)
        return parse_employees(records)


_SELECT_EMPLOYEES = sql.SQL(
    """
    SELECT id, "Employee_ID", "Employee_Name", "Role", "Status"
    FROM {schema}."Employee Data"
    WHERE "Employee_Name" IS NOT NULL
    """
)


@final
class NocoDBPostgresEmployeeSource:
    def __init__(self, dsn: str, base_id: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._base_id = base_id
        self._connect_timeout_seconds = connect_timeout_seconds

    async def load(self) -> tuple[Employee, ...]:
        records = await run_sync(self._load)
        return parse_employees(records)

    def _load(self) -> list[dict[str, JsonValue]]:
        query = _SELECT_EMPLOYEES.format(schema=sql.Identifier(self._base_id))
        with (
            psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds) as connection,
            connection.cursor() as cursor,
        ):
            _ = cursor.execute(query)
            rows = cursor.fetchall()
        return [
            dict(
                zip(
                    ("Id", "Employee ID", "Employee Name", "Role", "Status"),
                    row,
                    strict=True,
                )
            )
            for row in rows
        ]


_COLUMN_LETTERS: tuple[str, ...] = ("D", "E", "P", "F", "H", "K", "M")
_DEFAULT_SHEET_NAME = "Master Support Ticket MS"
_IOT_TEAM_ID = EmployeeId("IOT_TEAM")
_ISO_DATE_LENGTH: Final = 10


def _ranges(sheet_name: str) -> tuple[str, ...]:
    return tuple(f"'{sheet_name}'!{letter}:{letter}" for letter in _COLUMN_LETTERS)


def _cell_text(value: str | float | bool | None) -> str:
    return "" if value is None else str(value).strip()


def _parse_work_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    iso_date = _parse_date_pattern(text.replace("/", "-"), "%Y-%m-%d")
    if iso_date is not None:
        return iso_date
    if len(text) >= _ISO_DATE_LENGTH:
        iso_prefix = _parse_date_pattern(text[:_ISO_DATE_LENGTH].replace("/", "-"), "%Y-%m-%d")
        if iso_prefix is not None:
            return iso_prefix
    for pattern in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
        parsed = _parse_date_pattern(text, pattern)
        if parsed is not None:
            return parsed
    return None


def _parse_date_pattern(value: str, pattern: str) -> date | None:
    try:
        return datetime.strptime(value, pattern).replace(tzinfo=JAKARTA).date()
    except ValueError:
        return None


def _parse_datetime(value: str, work_date: date) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=JAKARTA)
        return parsed.astimezone(JAKARTA)
    for pattern in (
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%H:%M",
        "%H:%M:%S",
        "%I:%M %p",
        "%I:%M:%S %p",
    ):
        try:
            parsed_datetime = datetime.strptime(text, pattern).replace(tzinfo=JAKARTA)
            parsed_time = parsed_datetime.time()
            return datetime.combine(work_date, parsed_time, JAKARTA)
        except ValueError:
            continue
    return None


def _roll_forward(value: datetime | None, start_at: datetime | None) -> datetime | None:
    if value is None or start_at is None or value >= start_at:
        return value
    return value + timedelta(days=1)


def _first_column_value(value_range: _ValueRange, row_index: int) -> str:
    if not value_range.values or row_index >= len(value_range.values[0]):
        return ""
    return _cell_text(value_range.values[0][row_index])


def _responder(
    value: str,
    employees: Sequence[Employee],
) -> tuple[EmployeeId, str]:
    normalized = canonical_text(value)
    for employee in employees:
        if canonical_text(employee.name) == normalized:
            return employee.id, employee.name
    return _IOT_TEAM_ID, "IOT_TEAM"


def parse_iot_sheet(
    payload: GooglePayload,
    period: Period,
    employees: Sequence[Employee],
) -> tuple[IoTTaskInput, ...]:
    try:
        batch = _BatchValues.model_validate(payload)
    except ValidationError:
        return ()
    if len(batch.value_ranges) < len(_COLUMN_LETTERS):
        return ()
    row_count = max(
        (len(item.values[0]) for item in batch.value_ranges[:7] if item.values),
        default=0,
    )
    rows: list[IoTTaskInput] = []
    for row_index in range(row_count):
        values = tuple(_first_column_value(item, row_index) for item in batch.value_ranges[:7])
        work_date = _parse_work_date(values[0])
        if work_date is None or not (period.start <= work_date <= period.end):
            continue
        if not values[6].strip():
            continue
        employee_id, responder = _responder(values[4], employees)
        start_at = _parse_datetime(values[1], work_date)
        rows.append(
            IoTTaskInput(
                source_id=(f"{work_date.isoformat()}_{employee_id}_{canonical_text(values[6])}"),
                employee_id=employee_id,
                issue=values[6],
                issue_type=values[5],
                work_date=work_date,
                first_responder=responder,
                start_at=start_at,
                response_at=_roll_forward(_parse_datetime(values[3], work_date), start_at),
                close_at=_roll_forward(_parse_datetime(values[2], work_date), start_at),
            )
        )
    return tuple(rows)


@final
class GoogleIoTTaskSource:
    def __init__(
        self,
        reader: SheetBatchReader,
        spreadsheet_id: str,
        sheet_name: str = _DEFAULT_SHEET_NAME,
    ) -> None:
        self._reader = reader
        self._spreadsheet_id = spreadsheet_id
        self._ranges = _ranges(sheet_name)

    async def load(
        self,
        period: Period,
        employees: tuple[Employee, ...],
    ) -> tuple[IoTTaskInput, ...]:
        payload = await run_sync(
            self._reader.batch_get,
            self._spreadsheet_id,
            self._ranges,
        )
        return parse_iot_sheet(payload, period, employees)
