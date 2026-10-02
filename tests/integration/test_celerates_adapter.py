"""Celerates adapter v1 against a real PostgreSQL (TEST_DATABASE_DSN).

Closed loop inside ConForm: an actionable gap is visible through the adapter;
a Celerates-authored correction lands in the existing resolution table; the
PMO decision taken in Celerates is applied (and re-validated) by ConForm; the
projection, the next campaign snapshot and the canonical CSV all follow.
"""

from __future__ import annotations

import io
import os
from datetime import date, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.config import get_settings
from digital_bast.web import celerates_router as adapter

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TOKEN = "t" * 40
CYCLE = payroll_cycle(2026, 8)  # 2026-07-21 .. 2026-08-20, fully evaluated
GAP_DAY = date(2026, 8, 3)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    dsn = os.getenv("TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("TEST_DATABASE_DSN is not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=2) as connection:
            _ = connection.execute("SELECT 1")
    except psycopg.OperationalError as error:
        pytest.skip(f"TEST_DATABASE_DSN is unavailable: {error.sqlstate or 'connection failed'}")
    exports: Path = tmp_path_factory.mktemp("exports")
    saved = {
        k: os.environ.get(k)
        for k in (
            "APP_DATABASE_DSN",
            "CELERATES_SERVICE_TOKEN",
            "BAST_EXPORTS_DIR",
            "CELERATES_PUBLIC_URL",
        )
    }
    os.environ.update(
        {
            "APP_DATABASE_DSN": dsn,
            "CELERATES_SERVICE_TOKEN": TOKEN,
            "BAST_EXPORTS_DIR": str(exports),
            "CELERATES_PUBLIC_URL": "https://celerates.example",
        }
    )
    get_settings.cache_clear()
    adapter._configured.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    app = FastAPI()
    app.include_router(adapter.celerates_router(None))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        yield test_client
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    adapter._configured.cache_clear()


@pytest.fixture(scope="module")
def talent(client: TestClient) -> str:
    del client
    dsn = os.environ["APP_DATABASE_DSN"]
    suffix = uuid4().hex[:8]
    employee_id = f"MTG-TF/CEL-{suffix}"
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        # Other suites share this database; this cycle belongs to this module only.
        _ = cursor.execute(
            "UPDATE employees SET status = 'Inactive' WHERE employee_id NOT LIKE 'MTG-TF/CEL-%%'"
        )
        _ = cursor.execute(
            "UPDATE employees SET status = 'Inactive' WHERE employee_id LIKE 'MTG-TF/CEL-%%'"
        )
        _ = cursor.execute(
            "INSERT INTO employees (employee_id, nrp, full_name, role) "
            "VALUES (%s, %s, %s, 'Developer')",
            (employee_id, f"CEL{suffix}", f"Rina Synthetic {suffix}"),
        )
        _ = cursor.execute(
            "INSERT INTO wa_identity (wa_jid, employee_id) VALUES (%s, %s)",
            (f"62811{int(suffix, 16) % 10**8:08d}@c.us", employee_id),
        )
        day = CYCLE.period.start
        while day <= CYCLE.period.end:
            if day.weekday() < 5:
                _ = cursor.execute(
                    """
                    INSERT INTO attendance (record_key, employee_id, work_date, check_in, check_out)
                    VALUES (%s, %s, %s, %s, '17:00')
                    """,
                    (
                        f"attendance:{day.isoformat()}:{employee_id}",
                        employee_id,
                        day,
                        None if day == GAP_DAY else "08:00",
                    ),
                )
            day += timedelta(days=1)
    return employee_id


def headers(
    *, key: str | None = None, actor: str = "celerates:PMO Synthetic <pmo@example.test>"
) -> dict[str, str]:
    out = {"Authorization": f"Bearer {TOKEN}", "X-Celerates-Actor": actor}
    if key:
        out["Idempotency-Key"] = key
    return out


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (40, 90, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_service_token_is_required(client: TestClient) -> None:
    assert client.get("/api/celerates/v1/meta").status_code == 401
    wrong = client.get("/api/celerates/v1/meta", headers={"Authorization": "Bearer " + "x" * 40})
    assert wrong.json()["error"]["code"] == "unauthorized"
    meta = client.get("/api/celerates/v1/meta", headers=headers())
    assert meta.json()["api_version"] == "1"


def test_correction_closed_loop_through_the_adapter(client: TestClient, talent: str) -> None:
    period = {"year": 2026, "month": 8}
    readiness = client.get("/api/celerates/v1/readiness", params=period, headers=headers()).json()
    mine = next(item for item in readiness["talents"] if item["employee_id"] == talent)
    assert mine["status"] == "NEEDS_TALENT_ACTION"
    assert mine["whatsapp_bound"] is True
    assert readiness["cycle"]["id"] == CYCLE.cycle_id

    requirements = client.get(
        "/api/celerates/v1/talents/requirements",
        params={**period, "employee_id": talent},
        headers=headers(),
    ).json()["requirements"]
    assert [(r["work_date"], r["gap"], r["state"], r["allowed_actions"]) for r in requirements] == [
        (GAP_DAY.isoformat(), "missing_clock_in", "needs_action", ["worked"])
    ]

    campaign = client.post(
        "/api/celerates/v1/campaigns",
        json=period,
        headers=headers(key=f"campaign:{uuid4().hex}"),
    )
    assert campaign.status_code == 201, campaign.text
    assert [r["employee_id"] for r in campaign.json()["recipients"]] == [talent]

    form = {
        "employee_id": talent,
        "work_date": GAP_DAY.isoformat(),
        "action": "worked",
        "check_in": "08:00",
    }
    files = {"file": ("bukti.png", png(), "image/png")}
    key = f"correction:{uuid4().hex}"
    talent_actor = f"celerates-talent:{uuid4()}"
    submitted = client.post(
        "/api/celerates/v1/talents/attendance-corrections",
        data=form,
        files=files,
        headers=headers(key=key, actor=talent_actor),
    )
    assert submitted.status_code == 201, submitted.text
    correction_id = submitted.json()["correction_id"]
    replay = client.post(
        "/api/celerates/v1/talents/attendance-corrections",
        data=form,
        files={"file": ("bukti.png", png(), "image/png")},
        headers=headers(key=key, actor=talent_actor),
    )
    assert replay.headers.get("Idempotent-Replay") == "true"
    assert replay.json()["correction_id"] == correction_id
    conflict = client.post(
        "/api/celerates/v1/talents/attendance-corrections",
        data={**form, "check_in": "09:00"},
        files={"file": ("bukti.png", png(), "image/png")},
        headers=headers(key=key, actor=talent_actor),
    )
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    waiting = client.get(
        "/api/celerates/v1/talents/requirements",
        params={**period, "employee_id": talent},
        headers=headers(),
    ).json()["requirements"]
    assert [r["state"] for r in waiting] == ["waiting_review"]

    queue = client.get(
        "/api/celerates/v1/attendance-corrections", params=period, headers=headers()
    ).json()
    item = next(i for i in queue["items"] if i["id"] == correction_id)
    assert item["reviewable"] is True
    assert item["proposed_check_in"] == "08:00"
    evidence = client.get(
        f"/api/celerates/v1/attendance-corrections/{correction_id}/evidence", headers=headers()
    )
    assert evidence.headers["content-type"] == "image/png"

    reject_without_reason = client.post(
        f"/api/celerates/v1/attendance-corrections/{correction_id}/decision",
        json={"decision": "reject"},
        headers=headers(key=f"decision:{correction_id}:reject"),
    )
    assert reject_without_reason.status_code == 422
    decided = client.post(
        f"/api/celerates/v1/attendance-corrections/{correction_id}/decision",
        json={"decision": "approve"},
        headers=headers(key=f"decision:{correction_id}:approve"),
    ).json()
    assert decided == {
        "status": "succeeded",
        "outcome": "approved",
        "correction_status": "approved",
    }
    with psycopg.connect(os.environ["APP_DATABASE_DSN"]) as connection:
        row = connection.execute(
            "SELECT requested_by_jid, reviewed_by FROM attendance_resolution_requests "
            "WHERE id = %s",
            (correction_id,),
        ).fetchone()
    assert row == (talent_actor, "celerates:PMO Synthetic <pmo@example.test>")

    after = client.get(
        "/api/celerates/v1/talents/requirements",
        params={**period, "employee_id": talent},
        headers=headers(),
    ).json()
    assert after["requirements"] == []
    assert after["talent"]["status"] == "COMPLETE"

    next_campaign = client.post(
        "/api/celerates/v1/campaigns",
        json=period,
        headers=headers(key=f"campaign:{uuid4().hex}"),
    ).json()
    assert next_campaign["recipients"] == [], (
        "a resolved blocker is excluded from the next snapshot"
    )

    exported = client.post(
        "/api/celerates/v1/exports/attendance",
        json={**period, "report_type": "developer"},
        headers=headers(),
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["x-cycle-id"] == CYCLE.cycle_id
    line = next(
        text
        for text in exported.text.splitlines()
        if "03/08/2026" in text and talent.rsplit("/", maxsplit=1)[-1] in text
    )
    assert "08:00" in line, "the canonical CSV carries the approved correction"


def test_campaign_without_transport_auto_pauses(client: TestClient, talent: str) -> None:
    with psycopg.connect(os.environ["APP_DATABASE_DSN"]) as connection:
        _ = connection.execute(
            "UPDATE attendance SET check_out = NULL WHERE employee_id = %s AND work_date = %s",
            (talent, date(2026, 8, 4)),
        )
    period = {"year": 2026, "month": 8}
    created = client.post(
        "/api/celerates/v1/campaigns", json=period, headers=headers(key=f"campaign:{uuid4().hex}")
    ).json()
    campaign_id = created["id"]
    foreign = client.post(
        f"/api/celerates/v1/campaigns/{campaign_id}/approve",
        json={
            "links": [
                {
                    "employee_id": talent,
                    "url": "https://other.example/go/x",
                    "expires_at": "2099-01-01T00:00:00Z",
                }
            ]
        },
        headers=headers(key=f"approve:{campaign_id}:bad"),
    )
    assert foreign.json()["error"]["code"] in {"link_not_allowed", "invalid_link_expiry"}
    from datetime import UTC, datetime  # noqa: PLC0415

    expires = (datetime.now(UTC) + timedelta(hours=72)).isoformat()
    approved = client.post(
        f"/api/celerates/v1/campaigns/{campaign_id}/approve",
        json={
            "links": [
                {
                    "employee_id": talent,
                    "url": "https://celerates.example/go/abc",
                    "expires_at": expires,
                }
            ]
        },
        headers=headers(key=f"approve:{campaign_id}"),
    )
    assert approved.json()["state"] == "running", approved.text
    # Force the window open regardless of the wall clock for this check.
    with psycopg.connect(os.environ["APP_DATABASE_DSN"]) as connection:
        _ = connection.execute(
            "UPDATE celerates_campaigns SET window_start_hour = 0, window_end_hour = 24 "
            "WHERE id = %s",
            (campaign_id,),
        )
    report = client.post("/api/celerates/v1/campaigns/dispatch", headers=headers()).json()
    tick = next(item for item in report["campaigns"] if item["id"] == campaign_id)
    assert tick["pause_reason"] == "transport_unavailable"
    detail = client.get(f"/api/celerates/v1/campaigns/{campaign_id}", headers=headers()).json()
    assert detail["state"] == "paused"
    assert detail["recipients"][0]["state"] == "failed_retryable"
    assert any(event["event"] == "auto_paused" for event in detail["events"])
    control = client.put(
        "/api/celerates/v1/control",
        json={"kill_switch": True},
        headers=headers(key="control:kill:1"),
    ).json()
    assert control["kill_switch"] is True
    assert (
        client.post("/api/celerates/v1/campaigns/dispatch", headers=headers()).json()["killed"]
        is True
    )
    _ = client.put(
        "/api/celerates/v1/control",
        json={"kill_switch": False},
        headers=headers(key="control:kill:0"),
    )


CATEGORY = "Detail Aktivitas Waktu Rilis Fitur"


def test_attendance_log_tasks_and_direct_message(  # noqa: PLR0915 - one closed loop
    client: TestClient, talent: str
) -> None:
    from datetime import UTC, datetime  # noqa: PLC0415

    import anyio  # noqa: PLC0415

    from digital_bast.infrastructure.celerates_integration_store import (  # noqa: PLC0415
        PostgresCampaignStore,
    )

    dsn = os.environ["APP_DATABASE_DSN"]
    gap = date(2026, 8, 5)
    suffix = uuid4().hex[:8]
    task_keys = (f"redmine:cel-{suffix}:1", f"redmine:cel-{suffix}:2")
    with psycopg.connect(dsn) as connection:
        _ = connection.execute(
            "UPDATE attendance SET check_in = NULL WHERE employee_id = %s AND work_date = %s",
            (talent, gap),
        )
        _ = connection.execute(
            """
            INSERT INTO bast_evidence_rules
                (scope_key, task_category, evidence_required, updated_by)
            VALUES ('default', %s, true, 'test')
            ON CONFLICT (scope_key, task_category) DO UPDATE SET evidence_required = true
            """,
            (CATEGORY,),
        )
        for index, key in enumerate(task_keys, start=1):
            _ = connection.execute(
                """
                INSERT INTO tasks (record_key, employee_id, work_date, title, status, category,
                                   task_source, source_id)
                VALUES (%s, %s, %s, %s, 'Closed', %s, 'redmine', %s)
                """,
                (key, talent, date(2026, 8, 10 + index), f"Synthetic task {index}", CATEGORY, key),
            )
    period = {"year": 2026, "month": 8}

    log = client.get(
        "/api/celerates/v1/talents/attendance",
        params={**period, "employee_id": talent},
        headers=headers(),
    )
    assert log.status_code == 200, log.text
    body = log.json()
    assert body["source"] == "conform:pama"
    assert body["cycle"]["id"] == CYCLE.cycle_id
    days = {item["work_date"]: item for item in body["days"]}
    assert len(days) == (CYCLE.period.end - CYCLE.period.start).days + 1
    assert list(days) == sorted(days)
    open_day = days[gap.isoformat()]
    assert (open_day["state"], open_day["gap"], open_day["reason"]) == (
        "needs_action",
        "missing_clock_in",
        "GAP_UNCOVERED",
    )
    assert open_day["origin"] == "manual", "the edit trigger marks a direct write as manual"
    plain = days["2026-08-06"]
    assert (plain["state"], plain["gap"], plain["origin"], plain["check_in"]) == (
        "complete",
        None,
        "pipeline",
        "08:00",
    )
    corrected = days[GAP_DAY.isoformat()]
    assert corrected["state"] == "complete"
    assert corrected["correction"]["status"] == "approved"
    assert corrected["evidence_count"] == 1
    weekend = days["2026-08-01"]  # a Saturday without a source row
    assert (weekend["state"], weekend["origin"], weekend["gap"]) == ("not_required", None, None)

    tasks = client.get(
        "/api/celerates/v1/talents/tasks",
        params={**period, "employee_id": talent},
        headers=headers(),
    ).json()
    assert tasks["period"]["label"] == "Agustus 2026"
    assert tasks["summary"] == {"total": 2, "complete": 0, "missing": 2, "staged": 0}
    assert [item["task_key"] for item in tasks["items"]] == [task_keys[1], task_keys[0]]

    snapshot = client.post(
        "/api/celerates/v1/campaigns", json=period, headers=headers(key=f"campaign:{uuid4().hex}")
    ).json()
    mine = next(item for item in snapshot["recipients"] if item["employee_id"] == talent)
    assert mine["missing_tasks"] == 2, "the audience includes tasks without evidence"

    talent_actor = f"celerates-talent:{uuid4()}"
    key = f"task-evidence:{uuid4().hex}"
    form = {"employee_id": talent, "year": "2026", "month": "8", "caption": "bukti"}
    staged = client.post(
        f"/api/celerates/v1/talents/tasks/{task_keys[0]}/evidence",
        data=form,
        files={"file": ("bukti.png", png(), "image/png")},
        headers=headers(key=key, actor=talent_actor),
    )
    assert (staged.status_code, staged.json()) == (201, {"status": "staged"}), staged.text
    replay = client.post(
        f"/api/celerates/v1/talents/tasks/{task_keys[0]}/evidence",
        data=form,
        files={"file": ("bukti.png", png(), "image/png")},
        headers=headers(key=key, actor=talent_actor),
    )
    assert replay.headers.get("Idempotent-Replay") == "true"
    other = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(other, format="PNG")
    conflict = client.post(
        f"/api/celerates/v1/talents/tasks/{task_keys[0]}/evidence",
        data=form,
        files={"file": ("bukti.png", other.getvalue(), "image/png")},
        headers=headers(key=key, actor=talent_actor),
    )
    assert conflict.json()["error"]["code"] == "idempotency_conflict", "the hash covers the bytes"
    unknown = client.post(
        "/api/celerates/v1/talents/tasks/redmine:nope/evidence",
        data=form,
        files={"file": ("bukti.png", png(), "image/png")},
        headers=headers(key=f"task-evidence:{uuid4().hex}", actor=talent_actor),
    )
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "task_not_found")

    submitted = client.post(
        "/api/celerates/v1/talents/tasks/submit",
        json={"employee_id": talent, **period},
        headers=headers(key=f"task-submit:{uuid4().hex}", actor=talent_actor),
    )
    assert (submitted.status_code, submitted.json()) == (
        200,
        {"status": "submitted", "count": 1},
    ), submitted.text
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT e.submitted_by_jid FROM task_evidence e JOIN tasks t ON t.id = e.task_id "
            "WHERE t.record_key = %s",
            (task_keys[0],),
        ).fetchone()
    assert row == (talent_actor,), "the audit actor is X-Celerates-Actor"
    again = client.post(
        "/api/celerates/v1/talents/tasks/submit",
        json={"employee_id": talent, **period},
        headers=headers(key=f"task-submit:{uuid4().hex}", actor=talent_actor),
    )
    assert again.json()["error"]["code"] == "nothing_staged"
    after = client.get(
        "/api/celerates/v1/talents/tasks",
        params={**period, "employee_id": talent},
        headers=headers(),
    ).json()
    assert after["summary"] == {"total": 2, "complete": 1, "missing": 1, "staged": 0}
    assert [item["complete"] for item in after["items"]] == [False, True], "missing first"

    message = {
        "employee_id": talent,
        **period,
        "link": {"url": "https://celerates.example/go/dm", "expires_at": None},
    }
    no_transport = client.post(
        "/api/celerates/v1/talents/messages",
        json=message,
        headers=headers(key=f"message:{uuid4().hex}"),
    )
    assert no_transport.status_code == 503
    assert no_transport.json()["error"] == {
        "code": "transport_unavailable",
        "message": "WhatsApp transport is unavailable",
        "retryable": True,
    }
    _ = client.put(
        "/api/celerates/v1/control", json={"kill_switch": True}, headers=headers(key="kill:dm:1")
    )
    killed = client.post(
        "/api/celerates/v1/talents/messages",
        json=message,
        headers=headers(key=f"message:{uuid4().hex}"),
    )
    assert killed.json()["error"]["code"] == "kill_switch"
    _ = client.put(
        "/api/celerates/v1/control", json={"kill_switch": False}, headers=headers(key="kill:dm:0")
    )
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT status, actor, link_expires_at, missing_tasks FROM celerates_direct_messages "
            "WHERE employee_id = %s",
            (talent,),
        ).fetchall()
        assert rows == [("failed", "celerates:PMO Synthetic <pmo@example.test>", None, 1)]
        # As if the bridge had delivered it: the campaigns' 20 h dedupe and the
        # 10-minute direct dedupe both see it.
        _ = connection.execute(
            "UPDATE celerates_direct_messages SET status = 'sent', sent_at = now() "
            "WHERE employee_id = %s",
            (talent,),
        )
    recent = client.post(
        "/api/celerates/v1/talents/messages",
        json=message,
        headers=headers(key=f"message:{uuid4().hex}"),
    )
    assert recent.json()["error"]["code"] == "recently_sent"
    store = PostgresCampaignStore(dsn, payroll_cycle)
    since = datetime.now(UTC) - timedelta(hours=20)
    assert anyio.run(store.recent_send_exists, talent, since, uuid4()) is True
