from __future__ import annotations

from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.payroll_read import PayrollAttendanceRecord
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date, datetime, time

    from digital_bast.domain.completion import DateRange


class _PayrollAttendanceRow:
    __slots__ = (
        "absence_type",
        "attendance_id",
        "attendance_key",
        "check_in",
        "check_out",
        "employee_id",
        "evidence_count",
        "evidence_note",
        "proposed_check_in",
        "proposed_check_out",
        "rejection_reason",
        "resolution_id",
        "resolution_status",
        "resolution_type",
        "submitted_at",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors one bulk database row
        self,
        attendance_id: int,
        attendance_key: str,
        employee_id: str,
        work_date: date,
        check_in: time | None,
        check_out: time | None,
        evidence_note: str,
        evidence_count: int,
        resolution_id: str | None,
        resolution_status: str | None,
        resolution_type: str | None,
        absence_type: str | None,
        proposed_check_in: time | None,
        proposed_check_out: time | None,
        submitted_at: datetime | None,
        rejection_reason: str | None,
    ) -> None:
        self.attendance_id = attendance_id
        self.attendance_key = attendance_key
        self.employee_id = employee_id
        self.work_date = work_date
        self.check_in = check_in
        self.check_out = check_out
        self.evidence_note = evidence_note
        self.evidence_count = evidence_count
        self.resolution_id = resolution_id
        self.resolution_status = resolution_status
        self.resolution_type = resolution_type
        self.absence_type = absence_type
        self.proposed_check_in = proposed_check_in
        self.proposed_check_out = proposed_check_out
        self.submitted_at = submitted_at
        self.rejection_reason = rejection_reason


@final
class PostgresPayrollAttendanceReader:
    """Bulk Payroll attendance/correction projection reader for one cycle."""

    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def load(self, period: DateRange) -> tuple[PayrollAttendanceRecord, ...]:
        return await run_sync(self._load, period)

    def _load(self, period: DateRange) -> tuple[PayrollAttendanceRecord, ...]:
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout_seconds
                ) as connection,
                connection.cursor(row_factory=class_row(_PayrollAttendanceRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT a.id AS attendance_id,
                           a.record_key AS attendance_key,
                           a.employee_id,
                           a.work_date,
                           a.check_in,
                           a.check_out,
                           a.evidence_note,
                           COALESCE(ev.evidence_count, 0) AS evidence_count,
                           r.id::text AS resolution_id,
                           r.status AS resolution_status,
                           r.resolution_type,
                           r.absence_type,
                           r.proposed_check_in,
                           r.proposed_check_out,
                           r.submitted_at,
                           r.rejection_reason
                    FROM attendance a
                    LEFT JOIN LATERAL (
                        SELECT COUNT(*)::int AS evidence_count
                        FROM attendance_evidence ae
                        WHERE ae.attendance_id = a.id
                    ) ev ON true
                    LEFT JOIN LATERAL (
                        SELECT rr.id,
                               rr.status,
                               rr.resolution_type,
                               rr.absence_type,
                               rr.proposed_check_in,
                               rr.proposed_check_out,
                               rr.submitted_at,
                               rr.rejection_reason
                        FROM attendance_resolution_requests rr
                        WHERE rr.attendance_id = a.id
                        ORDER BY CASE rr.status
                                     WHEN 'approved' THEN 0
                                     WHEN 'pending' THEN 1
                                     ELSE 2
                                 END,
                                 COALESCE(rr.reviewed_at, rr.submitted_at) DESC
                        LIMIT 1
                    ) r ON true
                    WHERE a.work_date BETWEEN %s AND %s
                    ORDER BY a.employee_id, a.work_date, a.id
                    """,
                    (period.start, period.end),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="payroll_attendance_read"
            ) from error

        return tuple(
            PayrollAttendanceRecord(
                attendance_id=row.attendance_id,
                attendance_key=row.attendance_key,
                employee_id=row.employee_id,
                work_date=row.work_date,
                check_in=row.check_in,
                check_out=row.check_out,
                has_evidence=bool(row.evidence_note.strip()) or row.evidence_count > 0,
                resolution_id=row.resolution_id,
                resolution_status=row.resolution_status,
                resolution_type=row.resolution_type,
                absence_type=row.absence_type,
                proposed_check_in=row.proposed_check_in,
                proposed_check_out=row.proposed_check_out,
                submitted_at=row.submitted_at,
                rejection_reason=row.rejection_reason,
            )
            for row in rows
        )
