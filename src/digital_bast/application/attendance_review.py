"""Read-only evidence access for PMO attendance review surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

import psycopg
from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError


@dataclass(frozen=True, slots=True)
class AttendanceReviewEvidence:
    request_id: UUID
    evidence_id: UUID
    content_type: str
    byte_size: int
    caption: str
    uploaded_at: datetime
    content: bytes


@final
class AttendanceReviewService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def evidence(self, request_id: UUID) -> AttendanceReviewEvidence | None:
        return await run_sync(self._evidence, request_id)

    def _evidence(self, request_id: UUID) -> AttendanceReviewEvidence | None:
        try:
            with psycopg.connect(
                self._dsn, connect_timeout=self._connect_timeout_seconds
            ) as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT r.id,
                           ae.id,
                           ae.content_type,
                           ae.byte_size,
                           ae.caption,
                           ae.uploaded_at,
                           ae.image
                    FROM attendance_resolution_requests r
                    JOIN attendance_evidence ae ON ae.id = r.evidence_id
                    WHERE r.id = %s
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="attendance_review_evidence") from error
        if row is None:
            return None
        return AttendanceReviewEvidence(
            request_id=UUID(str(row[0])),
            evidence_id=UUID(str(row[1])),
            content_type=str(row[2]),
            byte_size=int(row[3]),
            caption=str(row[4] or ""),
            uploaded_at=row[5],
            content=bytes(row[6]),
        )
