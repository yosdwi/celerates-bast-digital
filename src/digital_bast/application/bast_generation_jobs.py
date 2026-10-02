"""Async job wrapper around operations.generate_bast() (application/bast_workflow.py's
readiness/audit-log concern stays untouched -- this owns only job lifecycle).

Reuses the `flow_runs` table: it already has the exact shape a generic job
queue needs (status enum, jsonb parameters/result, timestamps) and was
otherwise unreferenced by any app code. `flow_name='bast-generate'` scopes
rows here without needing a dedicated table or a migration.

Generation itself (headless-Chromium PDF render, ~150s for a full month) used
to run inline inside the HTTP request handling `POST /bast/generate`, which
upstream Cloudflare killed well before it finished (connections idle that
long get dropped at the edge, outside this app's control). Now the handler
only creates a `pending` row and schedules `execute()` as a FastAPI
BackgroundTask; the client polls `get()`/`list_recent()` until the row flips
to `succeeded`/`failed`, then downloads the artifact separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal, cast, final
from uuid import UUID, uuid4

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from digital_bast.application.bast_workflow import (
        BastGenerationMode,
        BastReadiness,
        BastWorkflowService,
    )
    from digital_bast.domain.completion import DateRange

_FLOW_NAME: Final = "bast-generate"
# Observed real generation time tops out around ~150s for a full month across
# every team; 10 minutes is a generous backstop against a row left stuck at
# pending/running by a mid-job container recreate (a blue/green redeploy, an
# OOM), not a tight SLA -- purely a read-time display fallback, no separate
# reconciliation process.
_STALE_AFTER: Final = timedelta(minutes=10)

JobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
DisplayStatus = Literal["pending", "running", "succeeded", "failed", "cancelled", "stale"]


@dataclass(frozen=True, slots=True)
class BastGenerationJob:
    id: UUID
    status: JobStatus
    parameters: dict[str, object]
    result: dict[str, object] | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def display_status(job: BastGenerationJob, *, now: datetime) -> DisplayStatus:
    if job.status in ("pending", "running") and now - job.created_at > _STALE_AFTER:
        return "stale"
    return job.status


class _JobRow:
    __slots__ = (
        "created_at",
        "error_code",
        "finished_at",
        "id",
        "parameters",
        "result",
        "started_at",
        "status",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - one field per selected column
        self,
        id: UUID,  # noqa: A002 - matches the column name
        status: str,
        parameters: dict[str, object],
        result: dict[str, object] | None,
        error_code: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.status = status
        self.parameters = parameters
        self.result = result
        self.error_code = error_code
        self.started_at = started_at
        self.finished_at = finished_at
        self.created_at = created_at


_SELECT_JOB = """
    SELECT id, status, parameters, result, error_code, started_at, finished_at, created_at
    FROM flow_runs WHERE id = %s AND flow_name = %s
"""


def _to_job(row: _JobRow) -> BastGenerationJob:
    return BastGenerationJob(
        id=row.id,
        status=cast("JobStatus", row.status),
        parameters=row.parameters,
        result=row.result,
        error_code=row.error_code,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


@final
class BastGenerationJobService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def create(  # noqa: PLR0913 - immutable job parameters snapshot
        self,
        *,
        report_type: str,
        year: int,
        month: int,
        mode: str,
        forced: bool,
        force_reason: str | None,
        requested_by: str,
    ) -> BastGenerationJob:
        parameters: dict[str, object] = {
            "report_type": report_type,
            "year": year,
            "month": month,
            "mode": mode,
            "force": forced,
            "force_reason": force_reason,
            "requested_by": requested_by,
        }
        return await run_sync(self._create, parameters)

    def _create(self, parameters: dict[str, object]) -> BastGenerationJob:
        job_id = uuid4()
        try:
            with self._connect() as connection, connection.cursor(row_factory=class_row(_JobRow)) as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO flow_runs (id, flow_name, status, parameters)
                    VALUES (%s, %s, 'pending', %s::jsonb)
                    RETURNING id, status, parameters, result, error_code, started_at, finished_at, created_at
                    """,
                    (job_id, _FLOW_NAME, json.dumps(parameters)),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="create_bast_generation_job") from error
        assert row is not None  # noqa: S101 - INSERT ... RETURNING always yields exactly one row
        return _to_job(row)

    async def mark_running(self, job_id: UUID) -> None:
        await run_sync(self._mark_running, job_id)

    def _mark_running(self, job_id: UUID) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE flow_runs SET status = 'running', started_at = now(), updated_at = now()
                    WHERE id = %s AND flow_name = %s
                    """,
                    (job_id, _FLOW_NAME),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="mark_bast_generation_job_running") from error

    async def mark_succeeded(self, job_id: UUID, *, artifact_name: str, fingerprint: str) -> None:
        await run_sync(self._mark_succeeded, job_id, artifact_name, fingerprint)

    def _mark_succeeded(self, job_id: UUID, artifact_name: str, fingerprint: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE flow_runs SET status = 'succeeded', finished_at = now(), updated_at = now(),
                        result = %s::jsonb
                    WHERE id = %s AND flow_name = %s
                    """,
                    (
                        json.dumps({"artifact_name": artifact_name, "fingerprint": fingerprint}),
                        job_id,
                        _FLOW_NAME,
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="mark_bast_generation_job_succeeded") from error

    async def mark_failed(self, job_id: UUID, *, error_code: str, error_message: str) -> None:
        await run_sync(self._mark_failed, job_id, error_code, error_message)

    def _mark_failed(self, job_id: UUID, error_code: str, error_message: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE flow_runs SET status = 'failed', finished_at = now(), updated_at = now(),
                        error_code = %s, result = %s::jsonb
                    WHERE id = %s AND flow_name = %s
                    """,
                    (error_code, json.dumps({"error_message": error_message}), job_id, _FLOW_NAME),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="mark_bast_generation_job_failed") from error

    async def get(self, job_id: UUID) -> BastGenerationJob | None:
        return await run_sync(self._get, job_id)

    def _get(self, job_id: UUID) -> BastGenerationJob | None:
        try:
            with self._connect() as connection, connection.cursor(row_factory=class_row(_JobRow)) as cursor:
                _ = cursor.execute(_SELECT_JOB, (job_id, _FLOW_NAME))
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="get_bast_generation_job") from error
        return None if row is None else _to_job(row)

    async def list_recent(self, *, limit: int = 20) -> tuple[BastGenerationJob, ...]:
        return await run_sync(self._list_recent, limit)

    def _list_recent(self, limit: int) -> tuple[BastGenerationJob, ...]:
        try:
            with self._connect() as connection, connection.cursor(row_factory=class_row(_JobRow)) as cursor:
                _ = cursor.execute(
                    """
                    SELECT id, status, parameters, result, error_code, started_at, finished_at, created_at
                    FROM flow_runs WHERE flow_name = %s ORDER BY created_at DESC LIMIT %s
                    """,
                    (_FLOW_NAME, limit),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="list_bast_generation_jobs") from error
        return tuple(_to_job(row) for row in rows)


async def execute(  # noqa: PLR0913 - background-task boundary needs the full request context
    job_id: UUID,
    jobs: BastGenerationJobService,
    bast_workflow: BastWorkflowService,
    *,
    selected_period: DateRange,
    report_type: str,
    generation_mode: BastGenerationMode,
    forced: bool,
    normalized_reason: str | None,
    readiness: BastReadiness,
    generated_by: str,
) -> None:
    from digital_bast.operations import generate_bast as generate_bast_artifact  # noqa: PLC0415

    await jobs.mark_running(job_id)
    try:
        path, report = await generate_bast_artifact(selected_period, report_type)
        _ = await bast_workflow.record_generation(
            report_type=report_type,
            period=selected_period,
            mode=generation_mode,
            forced=forced,
            force_reason=normalized_reason,
            readiness=readiness,
            generated_by=generated_by,
            artifact_name=path.name,
            fingerprint=report.fingerprint,
        )
        await jobs.mark_succeeded(job_id, artifact_name=path.name, fingerprint=report.fingerprint)
    except Exception as error:  # noqa: BLE001 - a background task can't propagate; must always resolve the row
        await jobs.mark_failed(job_id, error_code=type(error).__name__, error_message=str(error)[:500])
