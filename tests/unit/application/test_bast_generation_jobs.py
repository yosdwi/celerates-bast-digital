from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from digital_bast.application.bast_generation_jobs import BastGenerationJob, display_status

_NOW = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)


def _job(status: str, age: timedelta) -> BastGenerationJob:
    return BastGenerationJob(
        id=uuid4(),
        status=status,  # type: ignore[arg-type]
        parameters={},
        result=None,
        error_code=None,
        created_at=_NOW - age,
        started_at=None,
        finished_at=None,
    )


@pytest.mark.parametrize("status", ["pending", "running"])
def test_a_healthy_eleven_minute_render_is_not_shown_as_stale(status: str) -> None:
    # A September IoT report really took 659s (Oct 2026); the old 10 minute cut-off
    # showed it as "stalled" and told the user to try again, queueing a second render.
    assert display_status(_job(status, timedelta(minutes=11)), now=_NOW) == status


@pytest.mark.parametrize("status", ["pending", "running"])
def test_a_job_stuck_past_thirty_minutes_is_stale(status: str) -> None:
    assert display_status(_job(status, timedelta(minutes=31)), now=_NOW) == "stale"


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_finished_jobs_keep_their_status_however_old(status: str) -> None:
    assert display_status(_job(status, timedelta(days=3)), now=_NOW) == status
