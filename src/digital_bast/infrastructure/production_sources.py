from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, final

import pymssql
from anyio.to_thread import run_sync
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from digital_bast.domain.identity import canonical_text
from digital_bast.domain.models import Employee, EmployeeId
from digital_bast.domain.time import JAKARTA
from digital_bast.domain.transforms import IoTTaskInput, RedmineTaskInput
from digital_bast.infrastructure.errors import InfrastructureError, UpstreamTimeoutError

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from digital_bast.flows.models import Period
    from digital_bast.infrastructure.google import GooglePayload


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


class DateWindow(Protocol):
    """Just the bounds the parsers need. `Period` satisfies it, and so does the
    arbitrary start/end range the ingest endpoints receive from the bridge."""

    @property
    def start(self) -> date: ...

    @property
    def end(self) -> date: ...


class SheetBatchReader(Protocol):
    def batch_get(self, spreadsheet_id: str, ranges: tuple[str, ...]) -> GooglePayload: ...


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
    period: DateWindow,
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


# Schedule Shifting roster: month blocks laid out side by side (one ~31-column
# block per month, starting March 2024), a day-number row, then one row per
# IoT Operations employee. Column arithmetic and row offsets are lifted
# unchanged from scripts/import_schedule_csv.py (originally derived from
# scripts/load_pama_attendance.py::load_roster) -- that CSV importer imports
# this function rather than keeping its own copy, so there's only ever one
# place this layout gets parsed.

_SCHEDULE_ROSTER_START_YEAR: Final = 2024
_SCHEDULE_ROSTER_START_MONTH: Final = 3
_SCHEDULE_MONTH_HEADER_ROW: Final = 10
_SCHEDULE_DAY_NUMBER_ROW: Final = 12
_SCHEDULE_FIRST_DATA_ROW: Final = 13
_MONTHS_PER_YEAR: Final = 12


def parse_schedule_rows(  # noqa: C901 -- ported unchanged from import_schedule_csv.py
    rows: Sequence[Sequence[str]], names: dict[str, str]
) -> dict[tuple[str, date], str]:
    """`names` is {employee full name: employee_id}. Returns
    {(employee_id, work_date): raw PAMA roster code} -- resolve through
    pama_attendance.SHIFT_LEGEND for a display name, same as every other
    caller of that legend.
    """
    if len(rows) <= _SCHEDULE_DAY_NUMBER_ROW:
        return {}
    month_header = rows[_SCHEDULE_MONTH_HEADER_ROW]
    month_columns = [index for index, value in enumerate(month_header) if value.strip()]
    if not month_columns:
        return {}
    day_row = rows[_SCHEDULE_DAY_NUMBER_ROW]
    schedule: dict[tuple[str, date], str] = {}
    for row in rows[_SCHEDULE_FIRST_DATA_ROW:]:
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        # Row labels carry a suffix, e.g. "Titin Ervina Sari (P)".
        matched = next((name for name in names if name.lower() in label.lower()), None)
        if matched is None:
            continue
        if not any(value.strip() for value in row[1:]):
            continue
        boundaries = list(zip(month_columns, [*month_columns[1:], len(row)], strict=True))
        for block_index, (col_index, col_end) in enumerate(boundaries):
            total_month = (_SCHEDULE_ROSTER_START_MONTH - 1) + block_index
            year_num = _SCHEDULE_ROSTER_START_YEAR + total_month // _MONTHS_PER_YEAR
            month_num = total_month % _MONTHS_PER_YEAR + 1
            for offset in range(col_index, min(col_end, len(row))):
                day_text = day_row[offset].strip() if offset < len(day_row) else ""
                if not day_text.isdigit():
                    continue
                code = row[offset].strip()
                if not code:
                    continue
                try:
                    work_date = date(year_num, month_num, int(day_text))
                except ValueError:
                    continue
                schedule[(names[matched], work_date)] = code
    return schedule


type RedmineRow = dict[str, str | int | float | date | datetime | None]

_REDMINE_QUERY = """
SELECT login, nrp, nama, project_id, project_name, tracker_id, tracker_name,
       isu_id, isu_subject, description, start_date, due_date, created_on,
       closed_on, status_id, status_desc, author_id, author_name, done_ratio,
       estimated_hours, parent_id, updated_on
FROM DB_SATUPAMA_CIS.dbo.cis_jiep_tbl_redmine_bigdata_all_wi_digi
WHERE (start_date >= %s AND start_date <= %s) OR (created_on >= %s AND created_on <= %s)
ORDER BY start_date DESC, created_on DESC
"""


def _as_date(value: object) -> date | None:
    """Coerce a source date, whether it arrived as an object or as text.

    Both forms are real: the Prefect path gets native date/datetime objects
    straight from pymssql, while the /internal/sync ingest path receives the
    same rows as JSON, where every date is a string. Accepting only objects
    silently dropped 100% of ingested Redmine rows -- the row failed the
    `start_date is None` check below and hit a bare `continue`, with no error,
    no counter and no log. That is the same failure shape as the leading-"L"
    NRP typo, arriving through a different field.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class RedmineParseResult:
    """Parsed rows plus the NRPs that matched no employee.

    The unmatched set is not decoration: both importers join purely on NRP, and
    a silent `continue` here is what let a leading-"L" typo in three roster NRPs
    destroy 100% of those people's tasks and attendance without any error,
    counter, or log entry. Callers surface this.
    """

    rows: tuple[RedmineTaskInput, ...]
    unmatched_nrps: tuple[str, ...]
    # Rows dropped for reasons other than an unknown NRP: an unparsable or
    # out-of-window start_date, or a blank subject. Reported so a gap between
    # `received` and `upserted` has a stated cause rather than being a silent
    # subtraction someone has to go hunting for.
    dropped_bad_date: int = 0
    dropped_out_of_window: int = 0
    dropped_blank_title: int = 0


def parse_redmine_rows(
    rows: Sequence[RedmineRow],
    employees: Sequence[Employee],
    period: DateWindow,
) -> RedmineParseResult:
    nrp_to_employee = {employee.external_id: employee.id for employee in employees}
    results: list[RedmineTaskInput] = []
    unmatched: set[str] = set()
    bad_date = 0
    out_of_window = 0
    blank_title = 0
    for row in rows:
        nrp = row.get("nrp")
        employee_id = nrp_to_employee.get(str(nrp)) if nrp else None
        if employee_id is None:
            if nrp:
                unmatched.add(str(nrp))
            continue
        start_date = _as_date(row.get("start_date"))
        if start_date is None:
            bad_date += 1
            continue
        if not (period.start <= start_date <= period.end):
            out_of_window += 1
            continue
        title = str(row.get("isu_subject") or "").strip()
        if not title:
            blank_title += 1
            continue
        done_ratio = row.get("done_ratio")
        achievement = int(done_ratio) if isinstance(done_ratio, int | float) else 0
        results.append(
            RedmineTaskInput(
                source_id=str(row.get("isu_id")),
                employee_id=employee_id,
                title=title,
                requestor=str(row.get("author_name") or ""),
                status=str(row.get("status_desc") or ""),
                start_date=start_date,
                end_date=_as_date(row.get("due_date")),
                tracker=str(row.get("tracker_name") or ""),
                achievement=achievement,
            )
        )
    return RedmineParseResult(
        tuple(results),
        tuple(sorted(unmatched)),
        dropped_bad_date=bad_date,
        dropped_out_of_window=out_of_window,
        dropped_blank_title=blank_title,
    )


@final
class SqlServerRedmineTaskSource:
    def __init__(self, server: str, username: str, password: str, database: str) -> None:
        self._server = server
        self._username = username
        self._password = password
        self._database = database

    async def load(
        self,
        period: Period,
        employees: tuple[Employee, ...],
    ) -> tuple[RedmineTaskInput, ...]:
        rows = await run_sync(self._fetch, period)
        parsed = parse_redmine_rows(rows, employees, period)
        if parsed.unmatched_nrps:
            _LOGGER.warning(
                "redmine rows dropped: %d NRPs matched no employee: %s",
                len(parsed.unmatched_nrps),
                ", ".join(parsed.unmatched_nrps),
            )
        return parsed.rows

    def _fetch(self, period: Period) -> list[RedmineRow]:
        parameters = (period.start, period.end, period.start, period.end)
        try:
            with pymssql.connect(
                server=self._server,
                user=self._username,
                password=self._password,
                database=self._database,
                timeout=30,
                login_timeout=15,
            ) as connection:
                cursor = connection.cursor(as_dict=True)
                try:
                    cursor.execute(_REDMINE_QUERY, parameters)
                    return list(cursor.fetchall())
                finally:
                    cursor.close()
        except pymssql.OperationalError as error:
            if "timeout" in str(error).casefold():
                raise UpstreamTimeoutError(
                    service="sqlserver", operation="redmine_tasks"
                ) from error
            raise InfrastructureError(service="sqlserver", operation="redmine_tasks") from error
        except pymssql.Error as error:
            raise InfrastructureError(service="sqlserver", operation="redmine_tasks") from error
