"""Evidence upload over WhatsApp DM: candidate listing, bounded task selection,
and the upload transaction.

Business rule (matches V1, see docs/bast-e2e-plan.md §3.2): a task requires
evidence iff its status casefolds to 'closed' -- domain/completion.py::CLOSED_STATUS.
Task selection is a bounded choice over that employee's own outstanding tasks,
never free text resolved against the whole database -- see §3.5.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.domain.completion import CLOSED_STATUS
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date

_MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024


def sniff_content_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    task_source: str
    task_key: str
    title: str
    work_date: date
    evidence_count: int


def outstanding(candidates: tuple[EvidenceCandidate, ...]) -> tuple[EvidenceCandidate, ...]:
    return tuple(candidate for candidate in candidates if candidate.evidence_count == 0)


def select_by_caption(
    candidates: tuple[EvidenceCandidate, ...],
    caption: str,
) -> EvidenceCandidate | None:
    text = caption.strip().casefold()
    if not text:
        return None
    matches = [candidate for candidate in candidates if text in candidate.title.casefold()]
    return matches[0] if len(matches) == 1 else None


def select_by_index(
    candidates: tuple[EvidenceCandidate, ...], text: str
) -> EvidenceCandidate | None:
    stripped = text.strip()
    if not stripped.isdigit():
        return None
    index = int(stripped)
    if not 1 <= index <= len(candidates):
        return None
    return candidates[index - 1]


class UploadOutcome(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    NOT_FOUND = "not_found"
    NOT_OWNED = "not_owned"
    NOT_CLOSED = "not_closed"
    TOO_LARGE = "too_large"
    UNSUPPORTED_TYPE = "unsupported_type"


@dataclass(frozen=True, slots=True)
class UploadResult:
    outcome: UploadOutcome


class _CandidateRow:
    __slots__ = ("evidence_count", "task_key", "task_source", "title", "work_date")

    def __init__(
        self,
        task_source: str,
        task_key: str,
        title: str | None,
        work_date: date,
        evidence_count: int,
    ) -> None:
        self.task_source = task_source
        self.task_key = task_key
        self.title = title or ""
        self.work_date = work_date
        self.evidence_count = evidence_count


class _PendingRow:
    __slots__ = ("pending_task_key", "pending_task_source")

    def __init__(self, pending_task_source: str | None, pending_task_key: str | None) -> None:
        self.pending_task_source = pending_task_source
        self.pending_task_key = pending_task_key


class _TaskRow:
    __slots__ = ("employee_id", "status", "work_date")

    def __init__(self, employee_id: str | None, status: str | None, work_date: date) -> None:
        self.employee_id = employee_id
        self.status = status
        self.work_date = work_date


def _reject_task(row: _TaskRow, employee_id: str) -> UploadOutcome | None:
    if row.employee_id != employee_id:
        return UploadOutcome.NOT_OWNED
    if (row.status or "").strip().casefold() != CLOSED_STATUS:
        return UploadOutcome.NOT_CLOSED
    return None


@final
class EvidenceService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        return await run_sync(self._list_candidates, employee_id)

    async def pending_task(self, wa_jid: str) -> tuple[str, str] | None:
        return await run_sync(self._pending_task, wa_jid)

    async def set_pending(self, wa_jid: str, task_source: str, task_key: str) -> None:
        await run_sync(self._set_pending, wa_jid, task_source, task_key)

    async def clear_pending(self, wa_jid: str) -> None:
        await run_sync(self._clear_pending, wa_jid)

    async def upload(
        self,
        employee_id: str,
        task_source: str,
        task_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        return await run_sync(self._upload, employee_id, task_source, task_key, image, caption)

    def _list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_CandidateRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT d.source AS task_source, d.external_id AS task_key,
                           d.payload->>'title' AS title, d.work_date,
                           COUNT(e.id) AS evidence_count
                    FROM durable_records d
                    LEFT JOIN task_evidence e
                        ON e.task_source = d.source AND e.task_key = d.external_id
                    WHERE d.entity_kind = 'task'
                      AND d.payload->>'employee_id' = %s
                      AND lower(d.payload->>'status') = %s
                    GROUP BY d.source, d.external_id, d.payload->>'title', d.work_date
                    ORDER BY d.work_date, d.external_id
                    """,
                    (employee_id, CLOSED_STATUS),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="list_evidence_candidates"
            ) from error
        return tuple(
            EvidenceCandidate(
                row.task_source, row.task_key, row.title, row.work_date, row.evidence_count
            )
            for row in rows
        )

    def _pending_task(self, wa_jid: str) -> tuple[str, str] | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_PendingRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT pending_task_source, pending_task_key
                    FROM bot_conversations
                    WHERE wa_jid = %s AND updated_at > now() - interval '15 minutes'
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="load_pending_task") from error
        if row is None or row.pending_task_source is None or row.pending_task_key is None:
            return None
        return row.pending_task_source, row.pending_task_key

    def _set_pending(self, wa_jid: str, task_source: str, task_key: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (wa_jid, pending_task_source, pending_task_key)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_task_source = EXCLUDED.pending_task_source,
                        pending_task_key = EXCLUDED.pending_task_key,
                        updated_at = now()
                    """,
                    (wa_jid, task_source, task_key),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="set_pending_task") from error

    def _clear_pending(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute("DELETE FROM bot_conversations WHERE wa_jid = %s", (wa_jid,))
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="clear_pending_task") from error

    def _upload(
        self,
        employee_id: str,
        task_source: str,
        task_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        if len(image) > _MAX_IMAGE_BYTES:
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
                    SELECT payload->>'employee_id' AS employee_id, payload->>'status' AS status,
                           work_date
                    FROM durable_records
                    WHERE source = %s AND external_id = %s AND entity_kind = 'task'
                    FOR UPDATE
                    """,
                    (task_source, task_key),
                )
                row = cursor.fetchone()
                if row is None:
                    return UploadResult(UploadOutcome.NOT_FOUND)
                rejection = _reject_task(row, employee_id)
                if rejection is not None:
                    return UploadResult(rejection)
                try:
                    _ = cursor.execute(
                        """
                        INSERT INTO task_evidence (
                            task_source, task_key, employee_id, work_date,
                            caption, content_type, byte_size, sha256, image
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            task_source,
                            task_key,
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
            raise InfrastructureError(service="postgres", operation="upload_evidence") from error
