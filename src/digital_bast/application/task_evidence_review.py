"""Read-only Task List evidence access for the TalentOps PMO fast-look surface.

Task evidence has no approval lifecycle. This service only exposes evidence that
was already accepted by the talent upload flow, plus the task/talent context a
PMO needs to scan it before BAST generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import final
from uuid import UUID

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import dict_row

from digital_bast.domain.completion import DateRange
from digital_bast.infrastructure.errors import InfrastructureError


@dataclass(frozen=True, slots=True)
class TaskEvidenceItem:
    id: UUID
    employee_id: str
    nrp: str
    full_name: str
    role: str
    task_id: int
    work_date: date
    task_title: str
    task_source: str
    caption: str
    content_type: str
    byte_size: int
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class TaskEvidencePage:
    items: tuple[TaskEvidenceItem, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class TaskEvidenceContent:
    id: UUID
    content_type: str
    byte_size: int
    content: bytes


@final
class TaskEvidenceReviewService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def list_evidence(
        self,
        period: DateRange,
        *,
        nrp: str | None = None,
        limit: int = 60,
        offset: int = 0,
    ) -> TaskEvidencePage:
        return await run_sync(self._list_evidence, period, nrp, limit, offset)

    async def content(self, evidence_id: UUID) -> TaskEvidenceContent | None:
        return await run_sync(self._content, evidence_id)

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    def _list_evidence(
        self,
        period: DateRange,
        nrp: str | None,
        limit: int,
        offset: int,
    ) -> TaskEvidencePage:
        normalized_nrp = (nrp or "").strip()
        try:
            with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
                _ = cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM task_evidence te
                    JOIN tasks t ON t.id = te.task_id
                    JOIN employees e ON e.employee_id = te.employee_id
                    WHERE t.work_date BETWEEN %s AND %s
                      AND (%s = '' OR lower(e.nrp) = lower(%s))
                    """,
                    (period.start, period.end, normalized_nrp, normalized_nrp),
                )
                count_row = cursor.fetchone()
                total = 0 if count_row is None else int(count_row["total"])
                _ = cursor.execute(
                    """
                    SELECT te.id,
                           te.employee_id,
                           e.nrp,
                           e.full_name,
                           e.role,
                           t.id AS task_id,
                           t.work_date,
                           t.title AS task_title,
                           t.task_source,
                           te.caption,
                           te.content_type,
                           te.byte_size,
                           te.uploaded_at
                    FROM task_evidence te
                    JOIN tasks t ON t.id = te.task_id
                    JOIN employees e ON e.employee_id = te.employee_id
                    WHERE t.work_date BETWEEN %s AND %s
                      AND (%s = '' OR lower(e.nrp) = lower(%s))
                    ORDER BY te.uploaded_at DESC, te.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (
                        period.start,
                        period.end,
                        normalized_nrp,
                        normalized_nrp,
                        limit,
                        offset,
                    ),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="list_task_evidence_review") from error

        return TaskEvidencePage(
            items=tuple(
                TaskEvidenceItem(
                    id=UUID(str(row["id"])),
                    employee_id=str(row["employee_id"]),
                    nrp=str(row["nrp"]),
                    full_name=str(row["full_name"]),
                    role=str(row["role"]),
                    task_id=int(row["task_id"]),
                    work_date=row["work_date"],
                    task_title=str(row["task_title"]),
                    task_source=str(row["task_source"]),
                    caption=str(row["caption"] or ""),
                    content_type=str(row["content_type"]),
                    byte_size=int(row["byte_size"]),
                    uploaded_at=row["uploaded_at"],
                )
                for row in rows
            ),
            total=total,
            limit=limit,
            offset=offset,
        )

    def _content(self, evidence_id: UUID) -> TaskEvidenceContent | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT id, content_type, byte_size, image
                    FROM task_evidence
                    WHERE id = %s
                    """,
                    (evidence_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="task_evidence_content") from error
        if row is None:
            return None
        return TaskEvidenceContent(
            id=UUID(str(row[0])),
            content_type=str(row[1]),
            byte_size=int(row[2]),
            content=bytes(row[3]),
        )
