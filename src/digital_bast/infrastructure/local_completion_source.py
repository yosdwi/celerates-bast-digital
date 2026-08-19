"""Completion-check sources that read from durable_records / a local JSON
employee file instead of NocoDB. Used as a fallback when NOCODB_DATABASE_DSN
isn't configured -- see operations.create_local_completion_source.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.domain.completion import AttendanceFact
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

    from digital_bast.domain.completion import DateRange


@final
class LocalEmployeeSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self) -> tuple[Employee, ...]:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        role_by_name = {
            "Developer": EmployeeRole.DEVELOPER,
            "IoT Operation": EmployeeRole.IOT_OPERATIONS,
        }
        return tuple(
            Employee(
                id=EmployeeId(item["employee_id"]),
                external_id=item["nrp"],
                name=item["full_name"],
                role=role_by_name[item["role"]],
            )
            for item in raw
        )


class _AttendanceFactRow:
    __slots__ = ("check_in", "check_out", "employee_id", "work_date")

    def __init__(self, employee_id: str, work_date: date, check_in: str, check_out: str) -> None:
        self.employee_id = employee_id
        self.work_date = work_date
        self.check_in = check_in
        self.check_out = check_out


@final
class PostgresAttendanceFactReader:
    """Derives AttendanceFact from the flat 'attendance' rows scripts/load_pama_attendance.py
    writes. Evidence is never available from this source (no non-NocoDB source exists for
    it), so has_evidence is always False -- days without both punches surface as incomplete
    rather than being silently marked complete.
    """

    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def load(self, period: DateRange) -> dict[tuple[str, date], AttendanceFact]:
        return await run_sync(self._load, period)

    def _load(self, period: DateRange) -> dict[tuple[str, date], AttendanceFact]:
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout_seconds
                ) as connection,
                connection.cursor(row_factory=class_row(_AttendanceFactRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT payload->>'employee_id' AS employee_id,
                           work_date,
                           COALESCE(payload->>'check_in', '') AS check_in,
                           COALESCE(payload->>'check_out', '') AS check_out
                    FROM durable_records
                    WHERE entity_kind = 'attendance'
                      AND work_date BETWEEN %s AND %s
                    """,
                    (period.start, period.end),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="attendance_facts") from error
        return {
            (row.employee_id, row.work_date): AttendanceFact(
                work_date=row.work_date,
                has_clock_in=bool(row.check_in),
                has_clock_out=bool(row.check_out),
                has_evidence=False,
            )
            for row in rows
        }


class _TaskEvidenceCountRow:
    __slots__ = ("task_key", "total")

    def __init__(self, task_key: str, total: int) -> None:
        self.task_key = task_key
        self.total = total


@final
class PostgresTaskEvidenceReader:
    """Per-task evidence counts from task_evidence (talent uploads over WhatsApp DM,
    see bot/evidence.py), keyed by durable_records.external_id -- the same key
    domain Task records expose as str(task.key).
    """

    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def counts(self, period: DateRange) -> dict[str, int]:
        return await run_sync(self._counts, period)

    def _counts(self, period: DateRange) -> dict[str, int]:
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout_seconds
                ) as connection,
                connection.cursor(row_factory=class_row(_TaskEvidenceCountRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT task_key, COUNT(*) AS total
                    FROM task_evidence
                    WHERE work_date BETWEEN %s AND %s
                    GROUP BY task_key
                    """,
                    (period.start, period.end),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="task_evidence_counts"
            ) from error
        return {row.task_key: row.total for row in rows}
