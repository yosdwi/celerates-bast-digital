"""Conversation state for attendance-resolution DM workflow.

A Payroll reminder may now open a correction draft before evidence exists. The
draft is durable in ``bot_conversations`` and stores only explicit user-provided
proposal values. Raw attendance remains immutable and no PMO request is created
until the later review/submit step.

Legacy evidence-first behavior remains supported: marking evidence ready can
open the same draft shape, while preserving an existing proposal for the same
attendance identity instead of erasing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import cast, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.infrastructure.errors import InfrastructureError


@dataclass(frozen=True, slots=True)
class AttendanceResolutionDraft:
    attendance_key: str
    employee_id: str
    resolution_type: ResolutionType
    work_date: date | None = None
    proposed_check_in: time | None = None
    proposed_check_out: time | None = None
    absence_type: AbsenceType | None = None
    has_evidence: bool = False

    @property
    def has_proposal(self) -> bool:
        return (
            self.proposed_check_in is not None
            or self.proposed_check_out is not None
            or self.absence_type is not None
        )


class _DraftRow:
    __slots__ = (
        "absence_type",
        "attendance_key",
        "employee_id",
        "has_evidence",
        "proposed_check_in",
        "proposed_check_out",
        "resolution_type",
        "work_date",
    )

    def __init__(
        self,
        attendance_key: str,
        employee_id: str,
        work_date: date,
        resolution_type: str,
        proposed_check_in: time | None,
        proposed_check_out: time | None,
        absence_type: str | None,
        has_evidence: bool,
    ) -> None:
        self.attendance_key = attendance_key
        self.employee_id = employee_id
        self.work_date = work_date
        self.resolution_type = resolution_type
        self.proposed_check_in = proposed_check_in
        self.proposed_check_out = proposed_check_out
        self.absence_type = absence_type
        self.has_evidence = has_evidence


class _AttendanceGapRow:
    __slots__ = (
        "attendance_id",
        "check_in_missing",
        "check_out_missing",
        "employee_id",
        "has_evidence",
        "work_date",
    )

    def __init__(
        self,
        attendance_id: int,
        employee_id: str,
        work_date: date,
        check_in_missing: bool,
        check_out_missing: bool,
        has_evidence: bool,
    ) -> None:
        self.attendance_id = attendance_id
        self.employee_id = employee_id
        self.work_date = work_date
        self.check_in_missing = check_in_missing
        self.check_out_missing = check_out_missing
        self.has_evidence = has_evidence


def _resolution_type(row: _AttendanceGapRow) -> ResolutionType | None:
    if row.check_in_missing and not row.check_out_missing:
        return ResolutionType.MISSING_CLOCK_IN
    if row.check_out_missing and not row.check_in_missing:
        return ResolutionType.MISSING_CLOCK_OUT
    if row.check_in_missing and row.check_out_missing:
        # Placeholder while Talent chooses worked versus absence.
        return ResolutionType.MISSING_BOTH_WORKED
    return None


def _proposal_allowed(row: _AttendanceGapRow, resolution_type: ResolutionType) -> bool:
    expected = _resolution_type(row)
    if expected is None:
        return False
    if expected is ResolutionType.MISSING_BOTH_WORKED:
        return resolution_type in {ResolutionType.MISSING_BOTH_WORKED, ResolutionType.ABSENCE}
    return resolution_type is expected


def _valid_proposal_shape(
    resolution_type: ResolutionType,
    proposed_check_in: time | None,
    proposed_check_out: time | None,
    absence_type: AbsenceType | None,
) -> bool:
    if resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return (
            proposed_check_in is not None
            and proposed_check_out is None
            and absence_type is None
        )
    if resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return (
            proposed_check_in is None
            and proposed_check_out is not None
            and absence_type is None
        )
    if resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return (
            proposed_check_in is not None
            and proposed_check_out is not None
            and absence_type is None
        )
    if resolution_type is ResolutionType.ABSENCE:
        return absence_type is not None
    return False


def _draft_from_row(row: _DraftRow) -> AttendanceResolutionDraft:
    return AttendanceResolutionDraft(
        attendance_key=row.attendance_key,
        employee_id=row.employee_id,
        resolution_type=ResolutionType(row.resolution_type),
        work_date=row.work_date,
        proposed_check_in=row.proposed_check_in,
        proposed_check_out=row.proposed_check_out,
        absence_type=AbsenceType(row.absence_type) if row.absence_type is not None else None,
        has_evidence=row.has_evidence,
    )


@final
class AttendanceResolutionDmStateService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def begin(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft | None:
        return await run_sync(self._begin, wa_jid, employee_id, attendance_key)

    async def save_proposal(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        *,
        proposed_check_in: time | None = None,
        proposed_check_out: time | None = None,
        absence_type: AbsenceType | None = None,
    ) -> AttendanceResolutionDraft | None:
        return await run_sync(
            self._save_proposal,
            wa_jid,
            employee_id,
            attendance_key,
            resolution_type,
            proposed_check_in,
            proposed_check_out,
            absence_type,
        )

    async def mark_evidence_ready(
        self, wa_jid: str, employee_id: str, attendance_key: str
    ) -> AttendanceResolutionDraft | None:
        return await run_sync(self._mark_evidence_ready, wa_jid, employee_id, attendance_key)

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft | None:
        return await run_sync(self._pending, wa_jid)

    async def clear(self, wa_jid: str) -> None:
        await run_sync(self._clear, wa_jid)

    def _load_gap(
        self,
        cursor: psycopg.Cursor[tuple[object, ...]],
        attendance_key: str,
        employee_id: str,
        *,
        evidence_required: bool = False,
    ) -> _AttendanceGapRow | None:
        _ = cursor.execute(
            """
            SELECT a.id,
                   a.employee_id,
                   a.work_date,
                   a.check_in IS NULL AS check_in_missing,
                   a.check_out IS NULL AS check_out_missing,
                   EXISTS (
                       SELECT 1
                       FROM attendance_evidence ae
                       WHERE ae.attendance_id = a.id
                         AND ae.employee_id = a.employee_id
                   ) AS has_evidence
            FROM attendance a
            WHERE a.record_key = %s
              AND a.employee_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM attendance_resolution_requests r
                  WHERE r.attendance_id = a.id
                    AND r.status IN ('pending', 'approved')
              )
            FOR UPDATE OF a
            """,
            (attendance_key, employee_id),
        )
        raw = cursor.fetchone()
        if raw is None:
            return None
        row = _AttendanceGapRow(
            attendance_id=cast("int", raw[0]),
            employee_id=str(raw[1]),
            work_date=cast("date", raw[2]),
            check_in_missing=cast("bool", raw[3]),
            check_out_missing=cast("bool", raw[4]),
            has_evidence=cast("bool", raw[5]),
        )
        if evidence_required and not row.has_evidence:
            return None
        return row

    def _begin(
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
    ) -> AttendanceResolutionDraft | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                row = self._load_gap(cursor, attendance_key, employee_id)
                if row is None:
                    return None
                resolution_type = _resolution_type(row)
                if resolution_type is None:
                    return None
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (
                        wa_jid,
                        pending_attendance_id,
                        pending_attendance_resolution_type,
                        pending_absence_type,
                        pending_proposed_check_in,
                        pending_proposed_check_out,
                        pending_evidence_kind,
                        pending_task_id,
                        updated_at
                    ) VALUES (%s, %s, %s, NULL, NULL, NULL, 'attendance', NULL, now())
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_attendance_id = EXCLUDED.pending_attendance_id,
                        pending_attendance_resolution_type =
                            EXCLUDED.pending_attendance_resolution_type,
                        pending_absence_type = NULL,
                        pending_proposed_check_in = NULL,
                        pending_proposed_check_out = NULL,
                        pending_evidence_kind = 'attendance',
                        pending_task_id = NULL,
                        updated_at = now()
                    """,
                    (wa_jid, row.attendance_id, resolution_type.value),
                )
                return AttendanceResolutionDraft(
                    attendance_key=attendance_key,
                    employee_id=row.employee_id,
                    resolution_type=resolution_type,
                    work_date=row.work_date,
                    has_evidence=row.has_evidence,
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="begin_attendance_resolution_dm_state"
            ) from error

    def _save_proposal(  # noqa: PLR0913, PLR0917 - explicit proposal contract
        self,
        wa_jid: str,
        employee_id: str,
        attendance_key: str,
        resolution_type: ResolutionType,
        proposed_check_in: time | None,
        proposed_check_out: time | None,
        absence_type: AbsenceType | None,
    ) -> AttendanceResolutionDraft | None:
        if not _valid_proposal_shape(
            resolution_type,
            proposed_check_in,
            proposed_check_out,
            absence_type,
        ):
            return None
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT a.id,
                           a.employee_id,
                           a.work_date,
                           a.check_in IS NULL AS check_in_missing,
                           a.check_out IS NULL AS check_out_missing,
                           EXISTS (
                               SELECT 1
                               FROM attendance_evidence ae
                               WHERE ae.attendance_id = a.id
                                 AND ae.employee_id = a.employee_id
                           ) AS has_evidence
                    FROM bot_conversations c
                    JOIN attendance a ON a.id = c.pending_attendance_id
                    WHERE c.wa_jid = %s
                      AND a.record_key = %s
                      AND a.employee_id = %s
                      AND c.pending_attendance_resolution_type IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM attendance_resolution_requests r
                          WHERE r.attendance_id = a.id
                            AND r.status IN ('pending', 'approved')
                      )
                    FOR UPDATE OF c, a
                    """,
                    (wa_jid, attendance_key, employee_id),
                )
                raw = cursor.fetchone()
                if raw is None:
                    return None
                row = _AttendanceGapRow(
                    attendance_id=cast("int", raw[0]),
                    employee_id=str(raw[1]),
                    work_date=cast("date", raw[2]),
                    check_in_missing=cast("bool", raw[3]),
                    check_out_missing=cast("bool", raw[4]),
                    has_evidence=cast("bool", raw[5]),
                )
                if not _proposal_allowed(row, resolution_type):
                    return None
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET pending_attendance_resolution_type = %s,
                        pending_absence_type = %s,
                        pending_proposed_check_in = %s,
                        pending_proposed_check_out = %s,
                        pending_evidence_kind = 'attendance',
                        updated_at = now()
                    WHERE wa_jid = %s
                      AND pending_attendance_id = %s
                    """,
                    (
                        resolution_type.value,
                        absence_type.value if absence_type is not None else None,
                        proposed_check_in,
                        proposed_check_out,
                        wa_jid,
                        row.attendance_id,
                    ),
                )
                return AttendanceResolutionDraft(
                    attendance_key=attendance_key,
                    employee_id=row.employee_id,
                    resolution_type=resolution_type,
                    work_date=row.work_date,
                    proposed_check_in=proposed_check_in,
                    proposed_check_out=proposed_check_out,
                    absence_type=absence_type,
                    has_evidence=row.has_evidence,
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="save_attendance_resolution_dm_proposal"
            ) from error

    def _mark_evidence_ready(
        self, wa_jid: str, employee_id: str, attendance_key: str
    ) -> AttendanceResolutionDraft | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                row = self._load_gap(
                    cursor,
                    attendance_key,
                    employee_id,
                    evidence_required=True,
                )
                if row is None:
                    return None
                resolution_type = _resolution_type(row)
                if resolution_type is None:
                    return None
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (
                        wa_jid,
                        pending_attendance_id,
                        pending_attendance_resolution_type,
                        pending_evidence_kind,
                        updated_at
                    ) VALUES (%s, %s, %s, 'attendance', now())
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_attendance_id = EXCLUDED.pending_attendance_id,
                        pending_attendance_resolution_type = CASE
                            WHEN bot_conversations.pending_attendance_id =
                                 EXCLUDED.pending_attendance_id
                              AND bot_conversations.pending_attendance_resolution_type
                                  IS NOT NULL
                            THEN bot_conversations.pending_attendance_resolution_type
                            ELSE EXCLUDED.pending_attendance_resolution_type
                        END,
                        pending_absence_type = CASE
                            WHEN bot_conversations.pending_attendance_id =
                                 EXCLUDED.pending_attendance_id
                            THEN bot_conversations.pending_absence_type
                            ELSE NULL
                        END,
                        pending_proposed_check_in = CASE
                            WHEN bot_conversations.pending_attendance_id =
                                 EXCLUDED.pending_attendance_id
                            THEN bot_conversations.pending_proposed_check_in
                            ELSE NULL
                        END,
                        pending_proposed_check_out = CASE
                            WHEN bot_conversations.pending_attendance_id =
                                 EXCLUDED.pending_attendance_id
                            THEN bot_conversations.pending_proposed_check_out
                            ELSE NULL
                        END,
                        pending_evidence_kind = 'attendance',
                        pending_task_id = NULL,
                        updated_at = now()
                    """,
                    (wa_jid, row.attendance_id, resolution_type.value),
                )
            return self._pending(wa_jid)
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="mark_attendance_resolution_dm_ready"
            ) from error

    def _pending(self, wa_jid: str) -> AttendanceResolutionDraft | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DraftRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT a.record_key AS attendance_key,
                           a.employee_id,
                           a.work_date,
                           c.pending_attendance_resolution_type AS resolution_type,
                           c.pending_proposed_check_in AS proposed_check_in,
                           c.pending_proposed_check_out AS proposed_check_out,
                           c.pending_absence_type AS absence_type,
                           EXISTS (
                               SELECT 1
                               FROM attendance_evidence ae
                               WHERE ae.attendance_id = a.id
                                 AND ae.employee_id = a.employee_id
                           ) AS has_evidence
                    FROM bot_conversations c
                    JOIN attendance a ON a.id = c.pending_attendance_id
                    WHERE c.wa_jid = %s
                      AND c.pending_attendance_resolution_type IS NOT NULL
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
                return None if row is None else _draft_from_row(row)
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="load_attendance_resolution_dm_state"
            ) from error

    def _clear(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET pending_attendance_id = NULL,
                        pending_attendance_resolution_type = NULL,
                        pending_absence_type = NULL,
                        pending_proposed_check_in = NULL,
                        pending_proposed_check_out = NULL,
                        pending_evidence_kind = NULL,
                        updated_at = now()
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="clear_attendance_resolution_dm_state"
            ) from error
