"""Audited attendance-gap resolution workflow.

The client attendance row is the source of truth and is never updated here.
A request can only propose values for fields that are currently NULL. PMO
approval records an auditable decision; CSV export can project approved values
without mutating attendance.check_in/check_out, while BAST keeps rendering the
raw attendance plus evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import TYPE_CHECKING, final
from uuid import UUID

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import datetime


class ResolutionType(StrEnum):
    MISSING_CLOCK_IN = "missing_clock_in"
    MISSING_CLOCK_OUT = "missing_clock_out"
    MISSING_BOTH_WORKED = "missing_both_worked"
    ABSENCE = "absence"


class AbsenceType(StrEnum):
    CUTI = "cuti"
    IZIN = "izin"
    SAKIT = "sakit"


class ResolutionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SubmitOutcome(StrEnum):
    CREATED = "created"
    NOT_FOUND = "not_found"
    NOT_OWNED = "not_owned"
    SOURCE_NOT_ELIGIBLE = "source_not_eligible"
    EVIDENCE_REQUIRED = "evidence_required"
    ALREADY_OPEN = "already_open"
    INVALID_REQUEST = "invalid_request"


class DecisionOutcome(StrEnum):
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    ALREADY_RESOLVED = "already_resolved"
    SOURCE_CHANGED = "source_changed"
    REJECTION_REASON_REQUIRED = "rejection_reason_required"


@dataclass(frozen=True, slots=True)
class SubmitResult:
    outcome: SubmitOutcome
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DecisionResult:
    outcome: DecisionOutcome
    status: ResolutionStatus | None = None


@dataclass(frozen=True, slots=True)
class AttendanceResolution:
    id: UUID
    attendance_id: int
    employee_id: str
    nrp: str
    full_name: str
    work_date: date
    resolution_type: ResolutionType
    absence_type: AbsenceType | None
    proposed_check_in: time | None
    proposed_check_out: time | None
    status: ResolutionStatus
    evidence_id: UUID
    requested_by_jid: str
    submitted_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None


class _AttendanceRow:
    __slots__ = ("attendance_id", "check_in", "check_out", "employee_id", "work_date")

    def __init__(
        self,
        attendance_id: int,
        employee_id: str,
        work_date: date,
        check_in: time | None,
        check_out: time | None,
    ) -> None:
        self.attendance_id = attendance_id
        self.employee_id = employee_id
        self.work_date = work_date
        self.check_in = check_in
        self.check_out = check_out


class _ResolutionRow:
    __slots__ = (
        "absence_type",
        "attendance_id",
        "employee_id",
        "evidence_id",
        "full_name",
        "id",
        "nrp",
        "proposed_check_in",
        "proposed_check_out",
        "rejection_reason",
        "requested_by_jid",
        "resolution_type",
        "reviewed_at",
        "reviewed_by",
        "status",
        "submitted_at",
        "work_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors one database row
        self,
        id: UUID,
        attendance_id: int,
        employee_id: str,
        nrp: str,
        full_name: str,
        work_date: date,
        resolution_type: str,
        absence_type: str | None,
        proposed_check_in: time | None,
        proposed_check_out: time | None,
        status: str,
        evidence_id: UUID,
        requested_by_jid: str,
        submitted_at: datetime,
        reviewed_by: str | None,
        reviewed_at: datetime | None,
        rejection_reason: str | None,
    ) -> None:
        self.id = id
        self.attendance_id = attendance_id
        self.employee_id = employee_id
        self.nrp = nrp
        self.full_name = full_name
        self.work_date = work_date
        self.resolution_type = resolution_type
        self.absence_type = absence_type
        self.proposed_check_in = proposed_check_in
        self.proposed_check_out = proposed_check_out
        self.status = status
        self.evidence_id = evidence_id
        self.requested_by_jid = requested_by_jid
        self.submitted_at = submitted_at
        self.reviewed_by = reviewed_by
        self.reviewed_at = reviewed_at
        self.rejection_reason = rejection_reason


def _eligible(row: _AttendanceRow, resolution_type: ResolutionType) -> bool:
    if resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return row.check_in is None and row.check_out is not None
    if resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return row.check_in is not None and row.check_out is None
    if resolution_type in (ResolutionType.MISSING_BOTH_WORKED, ResolutionType.ABSENCE):
        return row.check_in is None and row.check_out is None
    return False


def _valid_request_shape(
    resolution_type: ResolutionType,
    proposed_check_in: time | None,
    proposed_check_out: time | None,
    absence_type: AbsenceType | None,
) -> bool:
    if resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return proposed_check_in is not None and proposed_check_out is None and absence_type is None
    if resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return proposed_check_in is None and proposed_check_out is not None and absence_type is None
    if resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return proposed_check_in is not None and proposed_check_out is not None and absence_type is None
    if resolution_type is ResolutionType.ABSENCE:
        return proposed_check_in is None and proposed_check_out is None and absence_type is not None
    return False


def _to_resolution(row: _ResolutionRow) -> AttendanceResolution:
    return AttendanceResolution(
        id=row.id,
        attendance_id=row.attendance_id,
        employee_id=row.employee_id,
        nrp=row.nrp,
        full_name=row.full_name,
        work_date=row.work_date,
        resolution_type=ResolutionType(row.resolution_type),
        absence_type=AbsenceType(row.absence_type) if row.absence_type is not None else None,
        proposed_check_in=row.proposed_check_in,
        proposed_check_out=row.proposed_check_out,
        status=ResolutionStatus(row.status),
        evidence_id=row.evidence_id,
        requested_by_jid=row.requested_by_jid,
        submitted_at=row.submitted_at,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        rejection_reason=row.rejection_reason,
    )


_RESOLUTION_SELECT = """
    SELECT r.id,
           r.attendance_id,
           r.employee_id,
           e.nrp,
           e.full_name,
           r.work_date,
           r.resolution_type,
           r.absence_type,
           r.proposed_check_in,
           r.proposed_check_out,
           r.status,
           r.evidence_id,
           r.requested_by_jid,
           r.submitted_at,
           r.reviewed_by,
           r.reviewed_at,
           r.rejection_reason
    FROM attendance_resolution_requests r
    JOIN employees e ON e.employee_id = r.employee_id
"""


@final
class AttendanceResolutionService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def submit(
        self,
        employee_id: str,
        attendance_key: str,
        requested_by_jid: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: AbsenceType | None = None,
    ) -> SubmitResult:
        return await run_sync(
            self._submit,
            employee_id,
            attendance_key,
            requested_by_jid,
            resolution_type,
            proposed_check_in,
            proposed_check_out,
            absence_type,
        )

    async def pending(self) -> tuple[AttendanceResolution, ...]:
        return await run_sync(self._pending)

    async def for_employee(self, employee_id: str) -> tuple[AttendanceResolution, ...]:
        return await run_sync(self._for_employee, employee_id)

    async def decide(
        self,
        request_id: UUID,
        reviewer: str,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> DecisionResult:
        return await run_sync(self._decide, request_id, reviewer, approve, rejection_reason)

    def _load_attendance(
        self, cursor: psycopg.Cursor[tuple[object, ...]], attendance_key: str
    ) -> _AttendanceRow | None:
        with cursor.connection.cursor(row_factory=class_row(_AttendanceRow)) as rows:
            _ = rows.execute(
                """
                SELECT id AS attendance_id, employee_id, work_date, check_in, check_out
                FROM attendance
                WHERE record_key = %s
                FOR UPDATE
                """,
                (attendance_key,),
            )
            return rows.fetchone()

    def _submit(  # noqa: PLR0913, PLR0917
        self,
        employee_id: str,
        attendance_key: str,
        requested_by_jid: str,
        resolution_type: ResolutionType,
        proposed_check_in: time | None,
        proposed_check_out: time | None,
        absence_type: AbsenceType | None,
    ) -> SubmitResult:
        if not _valid_request_shape(
            resolution_type, proposed_check_in, proposed_check_out, absence_type
        ):
            return SubmitResult(SubmitOutcome.INVALID_REQUEST)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                row = self._load_attendance(cursor, attendance_key)
                if row is None:
                    return SubmitResult(SubmitOutcome.NOT_FOUND)
                if row.employee_id != employee_id:
                    return SubmitResult(SubmitOutcome.NOT_OWNED)
                if not _eligible(row, resolution_type):
                    return SubmitResult(SubmitOutcome.SOURCE_NOT_ELIGIBLE)
                _ = cursor.execute(
                    """
                    SELECT id
                    FROM attendance_evidence
                    WHERE attendance_id = %s AND employee_id = %s
                    ORDER BY uploaded_at DESC
                    LIMIT 1
                    """,
                    (row.attendance_id, employee_id),
                )
                evidence = cursor.fetchone()
                if evidence is None:
                    return SubmitResult(SubmitOutcome.EVIDENCE_REQUIRED)
                try:
                    _ = cursor.execute(
                        """
                        INSERT INTO attendance_resolution_requests (
                            attendance_id,
                            evidence_id,
                            employee_id,
                            work_date,
                            resolution_type,
                            absence_type,
                            proposed_check_in,
                            proposed_check_out,
                            requested_by_jid
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (
                            row.attendance_id,
                            evidence[0],
                            employee_id,
                            row.work_date,
                            resolution_type.value,
                            absence_type.value if absence_type is not None else None,
                            proposed_check_in,
                            proposed_check_out,
                            requested_by_jid,
                        ),
                    )
                    created = cursor.fetchone()
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return SubmitResult(SubmitOutcome.ALREADY_OPEN)
                except psycopg.errors.CheckViolation:
                    connection.rollback()
                    return SubmitResult(SubmitOutcome.INVALID_REQUEST)
                return SubmitResult(
                    SubmitOutcome.CREATED,
                    UUID(str(created[0])) if created is not None else None,
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="submit_attendance_resolution"
            ) from error

    def _pending(self) -> tuple[AttendanceResolution, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_ResolutionRow)) as cursor,
            ):
                _ = cursor.execute(
                    _RESOLUTION_SELECT
                    + " WHERE r.status = 'pending' ORDER BY r.submitted_at, r.work_date, e.full_name"
                )
                return tuple(_to_resolution(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="list_pending_attendance_resolutions"
            ) from error

    def _for_employee(self, employee_id: str) -> tuple[AttendanceResolution, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_ResolutionRow)) as cursor,
            ):
                _ = cursor.execute(
                    _RESOLUTION_SELECT
                    + " WHERE r.employee_id = %s ORDER BY r.submitted_at DESC",
                    (employee_id,),
                )
                return tuple(_to_resolution(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="list_employee_attendance_resolutions"
            ) from error

    def _decide(
        self,
        request_id: UUID,
        reviewer: str,
        approve: bool,
        rejection_reason: str | None,
    ) -> DecisionResult:
        if not approve and not (rejection_reason or "").strip():
            return DecisionResult(DecisionOutcome.REJECTION_REASON_REQUIRED)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT r.status, r.resolution_type,
                           a.check_in, a.check_out
                    FROM attendance_resolution_requests r
                    JOIN attendance a ON a.id = r.attendance_id
                    WHERE r.id = %s
                    FOR UPDATE OF r, a
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return DecisionResult(DecisionOutcome.NOT_FOUND)
                status = ResolutionStatus(str(row[0]))
                if status is not ResolutionStatus.PENDING:
                    return DecisionResult(DecisionOutcome.ALREADY_RESOLVED, status)
                source = _AttendanceRow(
                    attendance_id=0,
                    employee_id="",
                    work_date=date.min,
                    check_in=row[2],
                    check_out=row[3],
                )
                if approve and not _eligible(source, ResolutionType(str(row[1]))):
                    return DecisionResult(DecisionOutcome.SOURCE_CHANGED)
                new_status = ResolutionStatus.APPROVED if approve else ResolutionStatus.REJECTED
                _ = cursor.execute(
                    """
                    UPDATE attendance_resolution_requests
                    SET status = %s,
                        reviewed_by = %s,
                        reviewed_at = now(),
                        rejection_reason = %s
                    WHERE id = %s
                    """,
                    (
                        new_status.value,
                        reviewer,
                        None if approve else rejection_reason.strip() if rejection_reason else None,
                        request_id,
                    ),
                )
                return DecisionResult(DecisionOutcome.UPDATED, new_status)
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="decide_attendance_resolution"
            ) from error
