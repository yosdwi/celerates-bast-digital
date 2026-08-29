"""Attendance evidence upload over WhatsApp DM: mirrors bot/evidence.py's Task
List evidence flow, but scoped to attendance days whose clock in/out is
incomplete and that don't have evidence yet (domain/completion.py's
EmployeeCompletion.log_1_pama_evidence_days already excludes off-days and days
with no attendance row at all -- see that field's docstring). Candidate
selection (by index or caption) and the stashed-photo-before-pick flow reuse
bot/evidence.py's helpers directly rather than duplicating them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.bot.evidence import (
    MAX_IMAGE_BYTES,
    UploadOutcome,
    UploadResult,
    sniff_content_type,
)
from digital_bast.domain.completion import format_day
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True, slots=True)
class AttendanceEvidenceCandidate:
    attendance_key: str
    work_date: date
    title: str
    evidence_count: int


def _candidate_title(work_date: date) -> str:
    return f"Attendance {format_day(work_date)}"


class _CandidateRow:
    __slots__ = ("evidence_count", "record_key", "work_date")

    def __init__(self, record_key: str, work_date: date, evidence_count: int) -> None:
        self.record_key = record_key
        self.work_date = work_date
        self.evidence_count = evidence_count


class _AttendanceRow:
    __slots__ = ("attendance_id", "employee_id", "work_date")

    def __init__(self, attendance_id: int, employee_id: str | None, work_date: date) -> None:
        self.attendance_id = attendance_id
        self.employee_id = employee_id
        self.work_date = work_date


@final
class AttendanceEvidenceService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def list_candidates(
        self, employee_id: str, dates: frozenset[date]
    ) -> tuple[AttendanceEvidenceCandidate, ...]:
        return await run_sync(self._list_candidates, employee_id, dates)

    async def pending_attendance(self, wa_jid: str) -> str | None:
        return await run_sync(self._pending_attendance, wa_jid)

    async def set_pending_attendance(self, wa_jid: str, attendance_key: str) -> None:
        await run_sync(self._set_pending_attendance, wa_jid, attendance_key)

    async def clear_pending_attendance(self, wa_jid: str) -> None:
        await run_sync(self._clear_pending_attendance, wa_jid)

    async def mark_active(self, wa_jid: str) -> None:
        # Mirrors EvidenceService.mark_active -- records "attendance" as the
        # most recently shown list, so a bare number reply before a specific
        # day is picked resolves against this pool, not the task pool.
        await run_sync(self._mark_active, wa_jid)

    async def upload(
        self, employee_id: str, attendance_key: str, image: bytes, caption: str
    ) -> UploadResult:
        return await run_sync(self._upload, employee_id, attendance_key, image, caption)

    def _list_candidates(
        self, employee_id: str, dates: frozenset[date]
    ) -> tuple[AttendanceEvidenceCandidate, ...]:
        if not dates:
            return ()
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_CandidateRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT a.record_key, a.work_date, COUNT(ae.id) AS evidence_count
                    FROM attendance a
                    LEFT JOIN attendance_evidence ae ON ae.attendance_id = a.id
                    WHERE a.employee_id = %s AND a.work_date = ANY(%s)
                    GROUP BY a.id
                    ORDER BY a.work_date
                    """,
                    (employee_id, list(dates)),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="list_attendance_evidence_candidates"
            ) from error
        return tuple(
            AttendanceEvidenceCandidate(
                row.record_key, row.work_date, _candidate_title(row.work_date), row.evidence_count
            )
            for row in rows
        )

    def _pending_attendance(self, wa_jid: str) -> str | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_CandidateRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT a.record_key, a.work_date, 0 AS evidence_count
                    FROM bot_conversations c
                    JOIN attendance a ON a.id = c.pending_attendance_id
                    WHERE c.wa_jid = %s
                      AND c.updated_at > now() - interval '15 minutes'
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="load_pending_attendance"
            ) from error
        return None if row is None else row.record_key

    def _set_pending_attendance(self, wa_jid: str, attendance_key: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                # Mirrors EvidenceService._set_pending -- picking an
                # attendance day clears any pending task selection, so the
                # two flows never both look "pending" at once.
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (wa_jid, pending_attendance_id)
                    SELECT %s, id FROM attendance WHERE record_key = %s
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_attendance_id = EXCLUDED.pending_attendance_id,
                        pending_task_id = NULL,
                        pending_evidence_kind = 'attendance',
                        updated_at = now()
                    """,
                    (wa_jid, attendance_key),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="set_pending_attendance"
            ) from error

    def _mark_active(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (wa_jid, pending_evidence_kind)
                    VALUES (%s, 'attendance')
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_evidence_kind = 'attendance',
                        updated_at = now()
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="mark_active_attendance"
            ) from error

    def _clear_pending_attendance(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET pending_attendance_id = NULL
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="clear_pending_attendance"
            ) from error

    def _upload(
        self, employee_id: str, attendance_key: str, image: bytes, caption: str
    ) -> UploadResult:
        if len(image) > MAX_IMAGE_BYTES:
            return UploadResult(UploadOutcome.TOO_LARGE)
        content_type = sniff_content_type(image)
        if content_type is None:
            return UploadResult(UploadOutcome.UNSUPPORTED_TYPE)
        digest = hashlib.sha256(image).hexdigest()
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_AttendanceRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT id AS attendance_id, employee_id, work_date
                    FROM attendance
                    WHERE record_key = %s
                    FOR UPDATE
                    """,
                    (attendance_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    return UploadResult(UploadOutcome.NOT_FOUND)
                if row.employee_id != employee_id:
                    return UploadResult(UploadOutcome.NOT_OWNED)
                try:
                    _ = cursor.execute(
                        """
                        INSERT INTO attendance_evidence (
                            attendance_id, employee_id, work_date,
                            caption, content_type, byte_size, sha256, image,
                            requires_resolution
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        """,
                        (
                            row.attendance_id,
                            employee_id,
                            row.work_date,
                            caption,
                            content_type,
                            len(image),
                            digest,
                            image,
                        ),
                    )
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return UploadResult(UploadOutcome.DUPLICATE)
                return UploadResult(UploadOutcome.STORED)
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="upload_attendance_evidence"
            ) from error
