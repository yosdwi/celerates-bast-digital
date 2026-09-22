"""Evidence adapters constrained by configured BAST evidence requirements.

Legacy evidence storage remains unchanged. These adapters only narrow which
Closed tasks are eligible for evidence based on the explicit category rule in
``bast_evidence_rules``. Unknown/unconfigured categories are not required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync

from digital_bast.bot.evidence import EvidenceCandidate, EvidenceService, UploadOutcome, UploadResult
from digital_bast.bot.task_evidence_submission import (
    TASK_EVIDENCE_SOURCES,
    TaskEvidenceCandidate,
    TaskEvidenceSubmissionService,
)
from digital_bast.domain.completion import CLOSED_STATUS
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.domain.completion import DateRange


@final
class RequiredTaskEvidencePolicy:
    def __init__(
        self,
        dsn: str,
        scope_key: str = "default",
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._dsn = dsn
        self._scope_key = scope_key
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def keys_for_employee(self, employee_id: str) -> frozenset[str]:
        return await run_sync(self._keys_for_employee, employee_id)

    async def required(self, employee_id: str, task_key: str) -> bool:
        return await run_sync(self._required, employee_id, task_key)

    def _keys_for_employee(self, employee_id: str) -> frozenset[str]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT t.record_key
                    FROM tasks t
                    JOIN bast_evidence_rules r
                      ON r.scope_key = %s
                     AND r.task_category = t.category
                     AND r.evidence_required = true
                    WHERE t.employee_id = %s
                      AND lower(t.status) = %s
                    """,
                    (self._scope_key, employee_id, CLOSED_STATUS),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="required_task_evidence_keys",
            ) from error
        return frozenset(str(row[0]) for row in rows)

    def _required(self, employee_id: str, task_key: str) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM tasks t
                        JOIN bast_evidence_rules r
                          ON r.scope_key = %s
                         AND r.task_category = t.category
                         AND r.evidence_required = true
                        WHERE t.employee_id = %s
                          AND t.record_key = %s
                          AND lower(t.status) = %s
                    )
                    """,
                    (self._scope_key, employee_id, task_key, CLOSED_STATUS),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="required_task_evidence_check",
            ) from error
        return bool(row and row[0])


@final
class RequirementAwareEvidenceService:
    """Legacy WhatsApp evidence service narrowed to required task categories."""

    def __init__(self, dsn: str, scope_key: str = "default") -> None:
        self._base = EvidenceService(dsn)
        self._policy = RequiredTaskEvidencePolicy(dsn, scope_key)

    async def list_candidates(self, employee_id: str) -> tuple[EvidenceCandidate, ...]:
        allowed = await self._policy.keys_for_employee(employee_id)
        return tuple(
            candidate
            for candidate in await self._base.list_candidates(employee_id)
            if candidate.task_key in allowed
        )

    async def pending_task(self, wa_jid: str) -> tuple[str, str] | None:
        return await self._base.pending_task(wa_jid)

    async def set_pending(self, wa_jid: str, task_key: str) -> None:
        await self._base.set_pending(wa_jid, task_key)

    async def clear_pending(self, wa_jid: str) -> None:
        await self._base.clear_pending(wa_jid)

    async def mark_active(self, wa_jid: str) -> None:
        await self._base.mark_active(wa_jid)

    async def active_kind(self, wa_jid: str) -> str | None:
        return await self._base.active_kind(wa_jid)

    async def stash_image(self, wa_jid: str, image: bytes, content_type: str, caption: str) -> None:
        await self._base.stash_image(wa_jid, image, content_type, caption)

    async def stashed_image(self, wa_jid: str) -> tuple[bytes, str, str] | None:
        return await self._base.stashed_image(wa_jid)

    async def clear_stashed_image(self, wa_jid: str) -> None:
        await self._base.clear_stashed_image(wa_jid)

    async def upload(
        self,
        employee_id: str,
        task_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        if not await self._policy.required(employee_id, task_key):
            return UploadResult(UploadOutcome.NOT_FOUND)
        return await self._base.upload(employee_id, task_key, image, caption)


@final
class RequirementAwareTaskEvidenceSubmissionService:
    """Talent Mobile staging/submission narrowed to required task categories."""

    def __init__(self, dsn: str, scope_key: str = "default", connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._scope_key = scope_key
        self._connect_timeout_seconds = connect_timeout_seconds
        self._base = TaskEvidenceSubmissionService(dsn, connect_timeout_seconds)
        self._policy = RequiredTaskEvidencePolicy(dsn, scope_key, connect_timeout_seconds)

    async def list_candidates(self, employee_id: str) -> tuple[TaskEvidenceCandidate, ...]:
        allowed = await self._policy.keys_for_employee(employee_id)
        return tuple(
            candidate
            for candidate in await self._base.list_candidates(employee_id)
            if candidate.task_key in allowed
        )

    async def stage(
        self,
        employee_id: str,
        task_key: str,
        image: bytes,
        caption: str,
    ) -> UploadResult:
        if not await self._policy.required(employee_id, task_key):
            return UploadResult(UploadOutcome.NOT_FOUND)
        return await self._base.stage(employee_id, task_key, image, caption)

    async def submit(self, employee_id: str, period: DateRange, jid: str) -> int:
        return await run_sync(self._submit, employee_id, period.start, period.end, jid)

    def _submit(
        self,
        employee_id: str,
        period_start: date,
        period_end: date,
        jid: str,
    ) -> int:
        try:
            with psycopg.connect(
                self._dsn,
                connect_timeout=self._connect_timeout_seconds,
            ) as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    WITH moved AS (
                        DELETE FROM task_evidence_staged s
                        USING tasks t, bast_evidence_rules r
                        WHERE s.task_id = t.id
                          AND r.scope_key = %s
                          AND r.task_category = t.category
                          AND r.evidence_required = true
                          AND s.employee_id = %s
                          AND s.work_date BETWEEN %s AND %s
                          AND t.employee_id = %s
                          AND lower(t.status) = %s
                          AND t.task_source IN (%s, %s)
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
                    ON CONFLICT (task_id, sha256) DO NOTHING
                    """,
                    (
                        self._scope_key,
                        employee_id,
                        period_start,
                        period_end,
                        employee_id,
                        CLOSED_STATUS,
                        *TASK_EVIDENCE_SOURCES,
                        jid,
                    ),
                )
                return max(cursor.rowcount, 0)
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="submit_required_task_evidence",
            ) from error
