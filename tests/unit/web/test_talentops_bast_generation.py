from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from digital_bast.application.bast_generation_jobs import BastGenerationJob
from digital_bast.application.bast_workflow import BastReadiness
from digital_bast.domain.completion import DateRange
from digital_bast.domain.models import EmployeeRole
from tests.unit.web.test_talentops_routes import make_client


class _BastWorkflow:
    async def readiness(self, period: DateRange, report_type: str) -> BastReadiness:
        _ = period
        return BastReadiness(
            report_type=report_type,
            role=EmployeeRole.IOT_OPERATIONS,
            total_talents=1,
            ready_talents=1,
            ready=True,
            blockers=(),
        )

    async def record_generation(self, **kwargs: object) -> UUID:
        assert kwargs["generated_by"] == "owner@example.com"
        assert kwargs["report_type"] == "iotoperation"
        return UUID("11111111-1111-4111-8111-111111111111")


class _FakeJobs:
    """In-memory stand-in for BastGenerationJobService, keyed like the real
    `flow_runs` table so the router's create -> background execute -> get/list
    round trip can be exercised without a database."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, BastGenerationJob] = {}

    async def create(  # noqa: PLR0913 - mirrors the real service's immutable parameter snapshot
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
        job = BastGenerationJob(
            id=uuid4(),
            status="pending",
            parameters={
                "report_type": report_type,
                "year": year,
                "month": month,
                "mode": mode,
                "force": forced,
                "force_reason": force_reason,
                "requested_by": requested_by,
            },
            result=None,
            error_code=None,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
        )
        self._jobs[job.id] = job
        return job

    async def mark_running(self, job_id: UUID) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(job, status="running", started_at=datetime.now(UTC))

    async def mark_succeeded(self, job_id: UUID, *, artifact_name: str, fingerprint: str) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(
            job,
            status="succeeded",
            finished_at=datetime.now(UTC),
            result={"artifact_name": artifact_name, "fingerprint": fingerprint},
        )

    async def mark_failed(self, job_id: UUID, *, error_code: str, error_message: str) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(
            job,
            status="failed",
            finished_at=datetime.now(UTC),
            error_code=error_code,
            result={"error_message": error_message},
        )

    async def get(self, job_id: UUID) -> BastGenerationJob | None:
        return self._jobs.get(job_id)

    async def list_recent(self, *, limit: int = 20) -> tuple[BastGenerationJob, ...]:
        ordered = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        return tuple(ordered)[:limit]


def test_bast_generation_creates_job_and_completes_in_background(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_generate_bast(
        period: DateRange,
        report_type: str,
    ) -> tuple[Path, SimpleNamespace]:
        assert period.start == date(2026, 8, 1)
        assert period.end == date(2026, 8, 31)
        assert report_type == "iotoperation"
        path = tmp_path / "BAST_iotoperation_2026-08.pdf"
        path.write_bytes(b"%PDF-1.4\nconform-test")
        return path, SimpleNamespace(fingerprint="fingerprint-test")

    workflow = _BastWorkflow()
    jobs = _FakeJobs()
    monkeypatch.setattr("digital_bast.operations.generate_bast", fake_generate_bast)
    monkeypatch.setattr("digital_bast.web.talentops_router._bast_workflow", lambda deps: workflow)
    monkeypatch.setattr("digital_bast.web.talentops_router._bast_jobs", lambda deps: jobs)
    client = make_client(authenticated=True)
    endpoint = "/api/talentops/v1/bast/generate?year=2026&month=8&report_type=iotoperation"

    missing_csrf = client.post(endpoint)
    created = client.post(endpoint, headers={"X-CSRF-Token": "csrf-token"})

    assert missing_csrf.status_code == 403
    assert created.status_code == 202
    body = created.json()
    assert body["report_type"] == "iotoperation"
    assert body["year"] == 2026
    assert body["month"] == 8

    # TestClient runs FastAPI's BackgroundTask before returning the response,
    # so the job has already finished by the time we poll for it.
    job_id = body["id"]
    finished = client.get(f"/api/talentops/v1/bast/generate/jobs/{job_id}")
    assert finished.status_code == 200
    finished_body = finished.json()
    assert finished_body["status"] == "succeeded"
    assert finished_body["display_status"] == "succeeded"
    assert finished_body["artifact_name"] == "BAST_iotoperation_2026-08.pdf"
    assert finished_body["fingerprint"] == "fingerprint-test"

    listed = client.get("/api/talentops/v1/bast/generate/jobs")
    assert listed.status_code == 200
    assert any(item["id"] == job_id for item in listed.json())


def test_bast_generation_job_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("digital_bast.web.talentops_router._bast_jobs", lambda deps: _FakeJobs())
    response = make_client(authenticated=True).get(
        f"/api/talentops/v1/bast/generate/jobs/{uuid4()}"
    )

    assert response.status_code == 404


def test_bast_generation_rejects_unknown_report_type() -> None:
    response = make_client(authenticated=True).post(
        "/api/talentops/v1/bast/generate?year=2026&month=8&report_type=shifting",
        headers={"X-CSRF-Token": "csrf-token"},
    )

    assert response.status_code == 422
