"""Conversation state for attendance-resolution DM workflow.

The selected attendance row remains in ``bot_conversations.pending_attendance_id``
after evidence upload while PMO correction details are collected. Unlike the
legacy 15-minute task/attendance *selection* state, a correction draft is kept
durable until it is submitted or explicitly cleared: the evidence itself is
durable, so silently expiring the draft could orphan stored evidence without
creating the auditable PMO request. The source attendance row itself is never
changed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.bot.attendance_resolution import ResolutionType
from digital_bast.infrastructure.errors import InfrastructureError


@dataclass(frozen=True, slots=True)
class AttendanceResolutionDraft:
    attendance_key: str
    employee_id: str
    resolution_type: ResolutionType


class _DraftRow:
    __slots__ = ("attendance_key", "employee_id", "resolution_type")

    def __init__(self, attendance_key: str, employee_id: str, resolution_type: str) -> None:
        self.attendance_key = attendance_key
        self.employee_id = employee_id
        self.resolution_type = resolution_type


class _AttendanceGapRow:
    __slots__ = ("attendance_id", "check_in_missing", "check_out_missing", "employee_id")

    def __init__(
        self,
        attendance_id: int,
        employee_id: str,
        check_in_missing: bool,
        check_out_missing: bool,
    ) -> None:
        self.attendance_id = attendance_id
        self.employee_id = employee_id
        self.check_in_missing = check_in_missing
        self.check_out_missing = check_out_missing


def _resolution_type(row: _AttendanceGapRow) -> ResolutionType | None:
    if row.check_in_missing and not row.check_out_missing:
        return ResolutionType.MISSING_CLOCK_IN
    if row.check_out_missing and not row.check_in_missing:
        return ResolutionType.MISSING_CLOCK_OUT
    if row.check_in_missing and row.check_out_missing:
        # Placeholder while the talent chooses "worked" versus absence. The
        # actual submitted request may still switch to ResolutionType.ABSENCE.
        return ResolutionType.MISSING_BOTH_WORKED
    return None


@final
class AttendanceResolutionDmStateService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def mark_evidence_ready(
        self, wa_jid: str, employee_id: str, attendance_key: str
    ) -> AttendanceResolutionDraft | None:
        return await run_sync(self._mark_evidence_ready, wa_jid, employee_id, attendance_key)

    async def pending(self, wa_jid: str) -> AttendanceResolutionDraft | None:
        return await run_sync(self._pending, wa_jid)

    async def clear(self, wa_jid: str) -> None:
        await run_sync(self._clear, wa_jid)

    def _mark_evidence_ready(
        self, wa_jid: str, employee_id: str, attendance_key: str
    ) -> AttendanceResolutionDraft | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT a.id,
                           a.employee_id,
                           a.check_in IS NULL AS check_in_missing,
                           a.check_out IS NULL AS check_out_missing
                    FROM attendance a
                    WHERE a.record_key = %s
                      AND a.employee_id = %s
                      AND EXISTS (
                          SELECT 1
                          FROM attendance_evidence ae
                          WHERE ae.attendance_id = a.id
                      )
                    """,
                    (attendance_key, employee_id),
                )
                raw = cursor.fetchone()
                if raw is None:
                    return None
                row = _AttendanceGapRow(
                    attendance_id=int(raw[0]),
                    employee_id=str(raw[1]),
                    check_in_missing=bool(raw[2]),
                    check_out_missing=bool(raw[3]),
                )
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
                        pending_attendance_resolution_type = EXCLUDED.pending_attendance_resolution_type,
                        pending_absence_type = NULL,
                        pending_proposed_check_in = NULL,
                        pending_proposed_check_out = NULL,
                        pending_evidence_kind = 'attendance',
                        updated_at = now()
                    """,
                    (wa_jid, row.attendance_id, resolution_type.value),
                )
                return AttendanceResolutionDraft(attendance_key, row.employee_id, resolution_type)
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
                           c.pending_attendance_resolution_type AS resolution_type
                    FROM bot_conversations c
                    JOIN attendance a ON a.id = c.pending_attendance_id
                    WHERE c.wa_jid = %s
                      AND c.pending_attendance_resolution_type IS NOT NULL
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return AttendanceResolutionDraft(
                    row.attendance_key,
                    row.employee_id,
                    ResolutionType(row.resolution_type),
                )
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
