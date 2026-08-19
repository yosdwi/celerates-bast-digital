"""Evidence upload over WhatsApp DM: candidate listing, bounded task selection,
and the upload transaction.

Business rule (matches V1, see docs/bast-e2e-plan.md §3.2): a task requires
evidence iff its status casefolds to 'closed' -- domain/completion.py::CLOSED_STATUS.
Task selection is a bounded choice over that employee's own outstanding tasks,
never free text resolved against the whole database -- see §3.5.
"""

from __future__ import annotations

import hashlib
import re
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


_CAPTION_STOPWORDS: Final = frozenset(
    {
        "ini",
        "itu",
        "yang",
        "buat",
        "untuk",
        "dulu",
        "dong",
        "nih",
        "ya",
        "aku",
        "saya",
        "mau",
        "upload",
        "kirim",
        "foto",
        "gambar",
        "dokumen",
        "evidence",
        "task",
        "tasklist",
        "poin",
        "point",
        "nomor",
        "no",
    }
)
_KEYWORD_PATTERN: Final = re.compile(r"[a-z0-9]+")
_MIN_KEYWORD_LENGTH: Final = 3


def _keywords(text: str) -> frozenset[str]:
    return frozenset(
        word
        for word in _KEYWORD_PATTERN.findall(text.casefold())
        if len(word) >= _MIN_KEYWORD_LENGTH and word not in _CAPTION_STOPWORDS
    )


def select_by_caption_all(
    candidates: tuple[EvidenceCandidate, ...],
    caption: str,
) -> tuple[EvidenceCandidate, ...]:
    # Word-overlap, not substring containment: a caption is free text around
    # a title reference ("ini buat CCTV Gate" for title "CCTV Gate
    # Validation"), so the caption is neither a substring of the title nor
    # vice versa in general -- any shared distinctive word is enough.
    words = _keywords(caption)
    if not words:
        return ()
    return tuple(candidate for candidate in candidates if words & _keywords(candidate.title))


def select_by_caption(
    candidates: tuple[EvidenceCandidate, ...],
    caption: str,
) -> EvidenceCandidate | None:
    matches = select_by_caption_all(candidates, caption)
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
    __slots__ = ("employee_id", "status", "task_id", "work_date")

    def __init__(
        self, task_id: int, employee_id: str | None, status: str | None, work_date: date
    ) -> None:
        self.task_id = task_id
        self.employee_id = employee_id
        self.status = status
        self.work_date = work_date


class _StashedImageRow:
    __slots__ = ("pending_image", "pending_image_caption", "pending_image_content_type")

    def __init__(
        self,
        pending_image: bytes,
        pending_image_content_type: str,
        pending_image_caption: str | None,
    ) -> None:
        self.pending_image = pending_image
        self.pending_image_content_type = pending_image_content_type
        self.pending_image_caption = pending_image_caption


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

    async def set_pending(self, wa_jid: str, task_key: str) -> None:
        await run_sync(self._set_pending, wa_jid, task_key)

    async def clear_pending(self, wa_jid: str) -> None:
        await run_sync(self._clear_pending, wa_jid)

    async def stash_image(self, wa_jid: str, image: bytes, content_type: str, caption: str) -> None:
        await run_sync(self._stash_image, wa_jid, image, content_type, caption)

    async def stashed_image(self, wa_jid: str) -> tuple[bytes, str, str] | None:
        return await run_sync(self._stashed_image, wa_jid)

    async def clear_stashed_image(self, wa_jid: str) -> None:
        await run_sync(self._clear_stashed_image, wa_jid)

    async def upload(
        self,
        employee_id: str,
        task_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        return await run_sync(self._upload, employee_id, task_key, image, caption)

    def _list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_CandidateRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT t.task_source, t.record_key AS task_key,
                           t.title, t.work_date,
                           COUNT(e.id) AS evidence_count
                    FROM tasks t
                    LEFT JOIN task_evidence e ON e.task_id = t.id
                    WHERE t.employee_id = %s
                      AND lower(t.status) = %s
                    GROUP BY t.id, t.task_source, t.record_key, t.title, t.work_date
                    ORDER BY t.work_date, t.record_key
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
                    SELECT t.task_source AS pending_task_source,
                           t.record_key AS pending_task_key
                    FROM bot_conversations c
                    LEFT JOIN tasks t ON t.id = c.pending_task_id
                    WHERE c.wa_jid = %s
                      AND c.updated_at > now() - interval '15 minutes'
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="load_pending_task") from error
        if row is None or row.pending_task_source is None or row.pending_task_key is None:
            return None
        return row.pending_task_source, row.pending_task_key

    def _set_pending(self, wa_jid: str, task_key: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (wa_jid, pending_task_id)
                    SELECT %s, id FROM tasks WHERE record_key = %s
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_task_id = EXCLUDED.pending_task_id,
                        updated_at = now()
                    """,
                    (wa_jid, task_key),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="set_pending_task") from error

    def _clear_pending(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                # Null out just the task-selection columns, not the whole row --
                # a pending identity claim or a stashed draft image for this
                # same wa_jid (bot/identity.py, stash_image below) must survive.
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET pending_task_id = NULL
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="clear_pending_task") from error

    def _stash_image(self, wa_jid: str, image: bytes, content_type: str, caption: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations
                        (wa_jid, pending_image, pending_image_content_type, pending_image_caption)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_image = EXCLUDED.pending_image,
                        pending_image_content_type = EXCLUDED.pending_image_content_type,
                        pending_image_caption = EXCLUDED.pending_image_caption,
                        updated_at = now()
                    """,
                    (wa_jid, image, content_type, caption),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="stash_image") from error

    def _stashed_image(self, wa_jid: str) -> tuple[bytes, str, str] | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_StashedImageRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT pending_image, pending_image_content_type, pending_image_caption
                    FROM bot_conversations
                    WHERE wa_jid = %s AND updated_at > now() - interval '15 minutes'
                      AND pending_image IS NOT NULL
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="peek_stashed_image") from error
        if row is None:
            return None
        return row.pending_image, row.pending_image_content_type, row.pending_image_caption or ""

    def _clear_stashed_image(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET pending_image = NULL, pending_image_content_type = NULL,
                        pending_image_caption = NULL
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="clear_stashed_image"
            ) from error

    def _upload(
        self,
        employee_id: str,
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
                rejection = _reject_task(row, employee_id)
                if rejection is not None:
                    return UploadResult(rejection)
                try:
                    _ = cursor.execute(
                        """
                        INSERT INTO task_evidence (
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
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return UploadResult(UploadOutcome.DUPLICATE)
                return UploadResult(UploadOutcome.STORED)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="upload_evidence") from error
