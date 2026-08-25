"""Completion-check readers over the typed business tables.

LocalEmployeeSource stays as the seed/bootstrap reader for employee_data.json
(scripts/seed_employees_from_nocodb.py writes the `employees` table it
replaces); the live roster comes from infrastructure.postgres_employees.
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
        # employee_data.json historically wrote "IoT Operation" while the
        # EmployeeRole enum and NocoDB both say "IoT Operations". Accept both
        # so a roster file from either era loads.
        role_by_name = {
            "Developer": EmployeeRole.DEVELOPER,
            "IoT Operation": EmployeeRole.IOT_OPERATIONS,
            "IoT Operations": EmployeeRole.IOT_OPERATIONS,
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
    __slots__ = (
        "check_in",
        "check_out",
        "employee_id",
        "evidence_note",
        "evidence_photo_count",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917 -- one field per selected column
        self,
        employee_id: str,
        work_date: date,
        check_in: str,
        check_out: str,
        evidence_note: str,
        evidence_photo_count: int,
    ) -> None:
        self.employee_id = employee_id
        self.work_date = work_date
        self.check_in = check_in
        self.check_out = check_out
        self.evidence_note = evidence_note
        self.evidence_photo_count = evidence_photo_count


@final
class PostgresAttendanceFactReader:
    """Derives AttendanceFact from the `attendance` table.

    `evidence_note` is the human-maintained column NocoDB edits (it carries the
    old NocoDB "Evidence" text field). `evidence_photo_count` is the WhatsApp
    DM upload path (bot/attendance_evidence.py, attendance_evidence table) --
    either one satisfies has_evidence.
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
                    SELECT a.employee_id,
                           a.work_date,
                           COALESCE(to_char(a.check_in, 'HH24:MI'), '') AS check_in,
                           COALESCE(to_char(a.check_out, 'HH24:MI'), '') AS check_out,
                           a.evidence_note,
                           COUNT(ae.id) AS evidence_photo_count
                    FROM attendance a
                    LEFT JOIN attendance_evidence ae ON ae.attendance_id = a.id
                    WHERE a.work_date BETWEEN %s AND %s
                    GROUP BY a.id
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
                has_evidence=bool(row.evidence_note.strip()) or row.evidence_photo_count > 0,
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
    see bot/evidence.py), keyed by tasks.record_key -- the same key domain Task
    records expose as str(task.key).
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
                    SELECT t.record_key AS task_key, COUNT(*) AS total
                    FROM task_evidence e
                    JOIN tasks t ON t.id = e.task_id
                    WHERE e.work_date BETWEEN %s AND %s
                    GROUP BY t.record_key
                    """,
                    (period.start, period.end),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="task_evidence_counts"
            ) from error
        return {row.task_key: row.total for row in rows}
