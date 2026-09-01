"""Talent Mobile Task Evidence staging and final PMO submission.

The PMO guideline separates two actions: attach evidence to Closed Redmine
tasks, then explicitly "Ajukan ke PMO". Draft uploads are kept outside the
final task_evidence table so every existing readiness/BAST projection remains
blind to them. Final submission moves eligible drafts transactionally into the
final evidence table.

Legacy WhatsApp evidence continues through bot.evidence.EvidenceService and is
not changed by this service.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.bot.evidence import MAX_IMAGE_BYTES, UploadOutcome, UploadResult, sniff_content_type
from digital_bast.domain.completion import CLOSED_STATUS
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.domain.completion import DateRange


@dataclass(frozen=True, slots=True)
class TaskEvidenceCandidate:
    task_source: str
    task_key: str
    title: str
    work_date: date
    evidence_count: int
    staged_count: int


class _CandidateRow:
    __slots__ = (
        "evidence_count",
        "staged_count",
        "task_key",
        "task_source",
        "title",
        "work_date",
    )

    def __init__(
        self,
        task_source: str,
        task_key: str,
        title: str | None,
        work_date: date,
        evidence_count: int,
        staged_count: int,
    ) -> None:
        self.task_source = task_source
        self.task_key = task_key
        self.title = title or ""
        self.work_date = work_date
        self.evidence_count = evidence_count
        self.staged_count = staged_count


class _TaskRow:
    __slots__ = ("employee_id", "status", "task_id", "work_date")

    def __init__(
        self,
        task_id: int,
        employee_id: str | None,
        status: str | None,
        work_date: date,
    ) -> None:
        self.task_id = task_id
        self.employee_id = employee_id
        self.status = status
        self.work_date = work_date


@final
class TaskEvidenceSubmissionService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def list_candidates(self, employee_id: str) -> tuple[TaskEvidenceCandidate, ...]:
        return await run_sync(self._list_candidates, employee_id)

    async def stage(
        self,
        employee_id: str,
        task_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        return await run_sync(self._stage, employee_id, task_key, image, caption)

    async def submit(self, employee_id: str, period: DateRange, jid: str) -> int:
        return await run_sync(self._submit, employee_id, period, jid)

    def _list_candidates(self, employee_id: str) -> tuple[TaskEvidenceCandidate, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_CandidateRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT t.task_source,
                           t.record_key AS task_key,
                           t.title,
                           t.work_date,
                           (
                               SELECT COUNT(*)
                               FROM task_evidence e
                               WHERE e.task_id = t.id
                           ) AS evidence_count,
                           (
                               SELECT COUNT(*)
                               FROM task_evidence_staged s
                               WHERE s.task_id = t.id
                           ) AS staged_count
                    FROM tasks t
                    WHERE t.employee_id = %s
                      AND lower(t.status) = %s
                    ORDER BY t.work_date, t.record_key
                    """,
                    (employee_id, CLOSED_STATUS),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="list_task_evidence_submission_candidates"
            ) from error
        return tuple(
            TaskEvidenceCandidate(
                row.task_source,
                row.task_key,
                row.title,
                row.work_date,
                row.evidence_count,
                row.staged_count,
            )
            for row in rows
        )

    def _stage(
        self,
        employee_id: str,
        task_key: str,
        image: bytes,
        caption: str,
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
                connection.cursor(row_factory=class_row(_TaskRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT id AS task_id, employee_id, status, work_date
                    FROM tasks
                    WHERE record_key = %s
                    FOR UPDATE
                    """,
                    (task_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    return UploadResult(UploadOutcome.NOT_FOUND)
                if row.employee_id != employee_id:
                    return UploadResult(UploadOutcome.NOT_OWNED)
                if (row.status or "").strip().casefold() != CLOSED_STATUS:
                    return UploadResult(UploadOutcome.NOT_CLOSED)
                _ = cursor.execute(
                    """
                    INSERT INTO task_evidence_staged (
                        task_id, employee_id, work_date,
                        caption, content_type, byte_size, sha256, image
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.task_id,
                        employee_id,
                        row.work_date,
                        caption,
                        content_type,
                        len(image),
                        digest,
                        image,
                    ),
                )
                return UploadResult(UploadOutcome.STORED)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="stage_task_evidence") from error

    def _submit(self, employee_id: str, period: DateRange, jid: str) -> int:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    WITH moved AS (
                        DELETE FROM task_evidence_staged s
                        USING tasks t
                        WHERE s.task_id = t.id
                          AND s.employee_id = %s
                          AND s.work_date BETWEEN %s AND %s
                          AND t.employee_id = %s
                          AND lower(t.status) = %s
                        RETURNING
                            s.task_id,
                            s.employee_id,
                            s.work_date,
                            s.caption,
                            s.content_type,
                            s.byte_size,
                            s.sha256,
                            s.image
                    )
                    INSERT INTO task_evidence (
                        task_id, employee_id, work_date,
                        caption, content_type, byte_size, sha256, image,
                        submitted_at, submitted_by_jid
                    )
                    SELECT
                        task_id, employee_id, work_date,
                        caption, content_type, byte_size, sha256, image,
                        now(), %s
                    FROM moved
                    """,
                    (
                        employee_id,
                        period.start,
                        period.end,
                        employee_id,
                        CLOSED_STATUS,
                        jid,
                    ),
                )
                return max(cursor.rowcount, 0)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="submit_task_evidence") from error
