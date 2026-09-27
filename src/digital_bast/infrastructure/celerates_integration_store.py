"""PostgreSQL persistence for the Celerates integration adapter (v1).

Campaigns, recipients and their audit trail; command idempotency; the kill
switch; the PMO summary ledger; and two narrow reads the adapter needs
(bound WhatsApp identities as a boolean, and a correction's current status).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import TupleRow, dict_row
from psycopg.types.json import Jsonb

from digital_bast.application.celerates_campaigns import (
    Campaign,
    CampaignPolicy,
    CampaignState,
    Recipient,
    RecipientState,
)
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime
    from uuid import UUID

    from digital_bast.application.attendance_closing_policy import PayrollCycle

type Row = dict[str, Any]


def _connect(dsn: str) -> psycopg.Connection[TupleRow]:
    return psycopg.connect(dsn, connect_timeout=5)


@final
class PostgresCampaignStore:
    def __init__(self, dsn: str, cycle_for: Callable[[int, int], PayrollCycle]) -> None:
        self._dsn = dsn
        self._cycle_for = cycle_for

    # -- mapping ---------------------------------------------------------------
    def _campaign(self, row: Row) -> Campaign:
        return Campaign(
            id=cast("UUID", row["id"]),
            cycle_id=cast("str", row["cycle_id"]),
            cycle_year=cast("int", row["cycle_year"]),
            cycle_month=cast("int", row["cycle_month"]),
            cycle_label=self._cycle_for(
                cast("int", row["cycle_year"]), cast("int", row["cycle_month"])
            ).label,
            state=CampaignState(cast("str", row["state"])),
            policy=CampaignPolicy(
                window_start_hour=cast("int", row["window_start_hour"]),
                window_end_hour=cast("int", row["window_end_hour"]),
                batch_size=cast("int", row["batch_size"]),
                cooldown_seconds=cast("int", row["cooldown_seconds"]),
                min_interval_seconds=cast("int", row["min_interval_seconds"]),
                max_attempts=cast("int", row["max_attempts"]),
            ),
            created_by=cast("str", row["created_by"]),
            created_at=cast("datetime", row["created_at"]),
            next_dispatch_at=cast("datetime | None", row["next_dispatch_at"]),
            pause_reason=cast("str | None", row["pause_reason"]),
            approved_by=cast("str | None", row["approved_by"]),
            approved_at=cast("datetime | None", row["approved_at"]),
            finished_at=cast("datetime | None", row["finished_at"]),
        )

    @staticmethod
    def _recipient(row: Row) -> Recipient:
        return Recipient(
            id=cast("UUID", row["id"]),
            campaign_id=cast("UUID", row["campaign_id"]),
            employee_id=cast("str", row["employee_id"]),
            nrp=cast("str", row["nrp"]),
            name=cast("str", row["name"]),
            eligibility=cast("str", row["eligibility"]),
            actionable_days=cast("int", row["actionable_days"]),
            blocker_fingerprint=cast("str", row["blocker_fingerprint"]),
            state=RecipientState(cast("str", row["state"])),
            link_url=cast("str | None", row["link_url"]),
            link_expires_at=cast("datetime | None", row["link_expires_at"]),
            attempt_count=cast("int", row["attempt_count"]),
            last_error=cast("str | None", row["last_error"]),
            provider_message_id=cast("str | None", row["provider_message_id"]),
            sent_at=cast("datetime | None", row["sent_at"]),
        )

    # -- writes ----------------------------------------------------------------
    async def create(self, campaign: Campaign, recipients: tuple[Recipient, ...]) -> None:
        await run_sync(self._create, campaign, recipients)

    def _create(self, campaign: Campaign, recipients: tuple[Recipient, ...]) -> None:
        policy = campaign.policy
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_campaigns (
                        id, cycle_id, cycle_year, cycle_month, state, window_start_hour,
                        window_end_hour, batch_size, cooldown_seconds, min_interval_seconds,
                        max_attempts, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        campaign.id,
                        campaign.cycle_id,
                        campaign.cycle_year,
                        campaign.cycle_month,
                        policy.window_start_hour,
                        policy.window_end_hour,
                        policy.batch_size,
                        policy.cooldown_seconds,
                        policy.min_interval_seconds,
                        policy.max_attempts,
                        campaign.created_by,
                        campaign.created_at,
                    ),
                )
                for item in recipients:
                    _ = cursor.execute(
                        """
                        INSERT INTO celerates_campaign_recipients (
                            id, campaign_id, employee_id, nrp, name, eligibility,
                            actionable_days, blocker_fingerprint
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            item.id,
                            campaign.id,
                            item.employee_id,
                            item.nrp,
                            item.name,
                            item.eligibility,
                            item.actionable_days,
                            item.blocker_fingerprint,
                        ),
                    )
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_campaign_events (campaign_id, event, actor, detail)
                    VALUES (%s, 'created', %s, %s)
                    """,
                    (campaign.id, campaign.created_by, Jsonb({"recipients": len(recipients)})),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_campaign_create"
            ) from error

    async def save_campaign(self, campaign: Campaign, *, actor: str, event: str) -> None:
        await run_sync(self._save_campaign, campaign, actor, event)

    def _save_campaign(self, campaign: Campaign, actor: str, event: str) -> None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    UPDATE celerates_campaigns
                    SET state = %s, next_dispatch_at = %s, pause_reason = %s,
                        approved_by = %s, approved_at = %s, finished_at = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        campaign.state.value,
                        campaign.next_dispatch_at,
                        campaign.pause_reason,
                        campaign.approved_by,
                        campaign.approved_at,
                        campaign.finished_at,
                        campaign.id,
                    ),
                )
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_campaign_events (campaign_id, event, actor, detail)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        campaign.id,
                        event,
                        actor,
                        Jsonb(
                            {"state": campaign.state.value, "pause_reason": campaign.pause_reason}
                        ),
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_campaign_save"
            ) from error

    async def save_recipient(self, recipient: Recipient, *, actor: str, event: str) -> None:
        await run_sync(self._save_recipient, recipient, actor, event)

    def _save_recipient(self, recipient: Recipient, actor: str, event: str) -> None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    UPDATE celerates_campaign_recipients
                    SET state = %s, link_url = %s, link_expires_at = %s, attempt_count = %s,
                        last_error = %s, provider_message_id = %s, sent_at = %s,
                        actionable_days = %s, blocker_fingerprint = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        recipient.state.value,
                        recipient.link_url,
                        recipient.link_expires_at,
                        recipient.attempt_count,
                        recipient.last_error,
                        recipient.provider_message_id,
                        recipient.sent_at,
                        recipient.actionable_days,
                        recipient.blocker_fingerprint,
                        recipient.id,
                    ),
                )
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_campaign_events
                        (campaign_id, recipient_id, event, actor, detail)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        recipient.campaign_id,
                        recipient.id,
                        event,
                        actor,
                        Jsonb({"state": recipient.state.value, "error": recipient.last_error}),
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_recipient_save"
            ) from error

    # -- dispatch primitives ---------------------------------------------------
    async def lease_due(self, now: datetime, lease_until: datetime) -> tuple[Campaign, ...]:
        return await run_sync(self._lease_due, now, lease_until)

    def _lease_due(self, now: datetime, lease_until: datetime) -> tuple[Campaign, ...]:
        # The lease (next_dispatch_at pushed forward atomically) makes one tick own
        # a campaign; a concurrent tick sees it as not due.
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    UPDATE celerates_campaigns
                    SET next_dispatch_at = %s, updated_at = now()
                    WHERE state = 'running'
                      AND (next_dispatch_at IS NULL OR next_dispatch_at <= %s)
                    RETURNING *
                    """,
                    (lease_until, now),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_lease") from error
        return tuple(self._campaign(row) for row in rows)

    async def claim(self, recipient_id: UUID) -> bool:
        return await run_sync(self._claim, recipient_id)

    def _claim(self, recipient_id: UUID) -> bool:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    UPDATE celerates_campaign_recipients
                    SET state = 'sending', updated_at = now()
                    WHERE id = %s AND state IN ('pending', 'failed_retryable')
                    RETURNING id
                    """,
                    (recipient_id,),
                )
                return cursor.fetchone() is not None
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_claim") from error

    async def recover_interrupted(self, campaign_id: UUID) -> int:
        return await run_sync(self._recover_interrupted, campaign_id)

    def _recover_interrupted(self, campaign_id: UUID) -> int:
        # Only the leased tick dispatches a campaign, so a row still 'sending' at
        # tick start was claimed by a tick that died mid-send: never resend it.
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    UPDATE celerates_campaign_recipients
                    SET state = 'unknown', last_error = 'interrupted_after_send_claim',
                        updated_at = now()
                    WHERE campaign_id = %s AND state = 'sending'
                    RETURNING id
                    """,
                    (campaign_id,),
                )
                rows = cursor.fetchall()
                for row in rows:
                    _ = cursor.execute(
                        """
                        INSERT INTO celerates_campaign_events
                            (campaign_id, recipient_id, event, actor)
                        VALUES (%s, %s, 'recipient_unknown', 'dispatcher')
                        """,
                        (campaign_id, row["id"]),
                    )
                return len(rows)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_recover") from error

    async def recent_send_exists(
        self, employee_id: str, since: datetime, exclude_campaign: UUID
    ) -> bool:
        return await run_sync(self._recent_send_exists, employee_id, since, exclude_campaign)

    def _recent_send_exists(self, employee_id: str, since: datetime, exclude: UUID) -> bool:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT 1 FROM celerates_campaign_recipients
                    WHERE employee_id = %s AND state = 'sent' AND sent_at >= %s
                      AND campaign_id <> %s
                    LIMIT 1
                    """,
                    (employee_id, since, exclude),
                )
                return cursor.fetchone() is not None
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_recent") from error

    async def kill_switch(self) -> bool:
        return (await PostgresIntegrationControl(self._dsn).get())[0]

    # -- reads -----------------------------------------------------------------
    async def get(self, campaign_id: UUID) -> tuple[Campaign, tuple[Recipient, ...]] | None:
        return await run_sync(self._get, campaign_id)

    def _get(self, campaign_id: UUID) -> tuple[Campaign, tuple[Recipient, ...]] | None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    "SELECT * FROM celerates_campaigns WHERE id = %s", (campaign_id,)
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                _ = cursor.execute(
                    """
                    SELECT * FROM celerates_campaign_recipients
                    WHERE campaign_id = %s ORDER BY name, employee_id
                    """,
                    (campaign_id,),
                )
                recipients = tuple(self._recipient(item) for item in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_campaign_get"
            ) from error
        return self._campaign(row), recipients

    async def list_recent(self, limit: int) -> tuple[tuple[Campaign, dict[str, int]], ...]:
        return await run_sync(self._list_recent, limit)

    def _list_recent(self, limit: int) -> tuple[tuple[Campaign, dict[str, int]], ...]:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    "SELECT * FROM celerates_campaigns ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                campaigns = [self._campaign(row) for row in cursor.fetchall()]
                out: list[tuple[Campaign, dict[str, int]]] = []
                for campaign in campaigns:
                    _ = cursor.execute(
                        """
                        SELECT state, count(*)::int AS n FROM celerates_campaign_recipients
                        WHERE campaign_id = %s GROUP BY state
                        """,
                        (campaign.id,),
                    )
                    out.append(
                        (
                            campaign,
                            {
                                cast("str", r["state"]): cast("int", r["n"])
                                for r in cursor.fetchall()
                            },
                        )
                    )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_campaign_list"
            ) from error
        return tuple(out)

    async def events(self, campaign_id: UUID, limit: int = 200) -> tuple[Row, ...]:
        return await run_sync(self._events, campaign_id, limit)

    def _events(self, campaign_id: UUID, limit: int) -> tuple[Row, ...]:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT id, recipient_id, event, actor, detail, created_at
                    FROM celerates_campaign_events WHERE campaign_id = %s
                    ORDER BY id DESC LIMIT %s
                    """,
                    (campaign_id, limit),
                )
                return tuple(cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_events") from error


@final
class PostgresIntegrationControl:
    def __init__(self, dsn: str, scope_key: str = "default") -> None:
        self._dsn = dsn
        self._scope = scope_key

    async def get(self) -> tuple[bool, str | None, datetime | None]:
        return await run_sync(self._get)

    def _get(self) -> tuple[bool, str | None, datetime | None]:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT kill_switch, updated_by, updated_at
                    FROM celerates_integration_control WHERE scope_key = %s
                    """,
                    (self._scope,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_control") from error
        if row is None:
            # A missing control row is treated as "stopped" -- fail closed.
            return True, None, None
        return (
            bool(row["kill_switch"]),
            cast("str | None", row["updated_by"]),
            cast("datetime | None", row["updated_at"]),
        )

    async def set(self, *, kill_switch: bool, actor: str) -> None:
        await run_sync(self._set, kill_switch, actor)

    def _set(self, kill_switch: bool, actor: str) -> None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_integration_control
                        (scope_key, kill_switch, updated_by, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (scope_key) DO UPDATE
                    SET kill_switch = EXCLUDED.kill_switch, updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    """,
                    (self._scope, kill_switch, actor),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_control_set"
            ) from error


@dataclass(frozen=True, slots=True)
class StoredResponse:
    request_hash: str
    status_code: int
    body: object


@final
class PostgresIdempotencyStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def get(self, key: str, route: str) -> StoredResponse | None:
        return await run_sync(self._get, key, route)

    def _get(self, key: str, route: str) -> StoredResponse | None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT request_hash, status_code, response FROM celerates_idempotency
                    WHERE idempotency_key = %s AND route = %s
                    """,
                    (key, route),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_idem_get") from error
        if row is None:
            return None
        body = row["response"]
        return StoredResponse(
            cast("str", row["request_hash"]),
            cast("int", row["status_code"]),
            json.loads(body) if isinstance(body, str) else cast("object", body),
        )

    async def put(  # noqa: PLR0913, PLR0917
        self, key: str, route: str, request_hash: str, status_code: int, body: object, actor: str
    ) -> None:
        await run_sync(self._put, key, route, request_hash, status_code, body, actor)

    def _put(  # noqa: PLR0913, PLR0917
        self, key: str, route: str, request_hash: str, status_code: int, body: object, actor: str
    ) -> None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_idempotency
                        (idempotency_key, route, request_hash, status_code, response, actor)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key, route) DO NOTHING
                    """,
                    (key, route, request_hash, status_code, Jsonb(body), actor),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_idem_put") from error


@dataclass(frozen=True, slots=True)
class CorrectionRecord:
    id: UUID
    employee_id: str
    work_date: date
    status: str
    resolution_type: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None


@final
class PostgresIntegrationReads:
    """Narrow reads the adapter needs that no existing service exposes."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def bound_employee_ids(self) -> frozenset[str]:
        return await run_sync(self._bound)

    def _bound(self) -> frozenset[str]:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute("SELECT employee_id FROM wa_identity")
                return frozenset(cast("str", row["employee_id"]) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="celerates_bound") from error

    async def correction(self, request_id: UUID) -> CorrectionRecord | None:
        return await run_sync(self._correction, request_id)

    def _correction(self, request_id: UUID) -> CorrectionRecord | None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT id, employee_id, work_date, status, resolution_type, reviewed_by,
                           reviewed_at, rejection_reason
                    FROM attendance_resolution_requests WHERE id = %s
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_correction"
            ) from error
        if row is None:
            return None
        return CorrectionRecord(
            id=cast("UUID", row["id"]),
            employee_id=cast("str", row["employee_id"]),
            work_date=cast("date", row["work_date"]),
            status=cast("str", row["status"]),
            resolution_type=cast("str", row["resolution_type"]),
            reviewed_by=cast("str | None", row["reviewed_by"]),
            reviewed_at=cast("datetime | None", row["reviewed_at"]),
            rejection_reason=cast("str | None", row["rejection_reason"]),
        )


@final
class PostgresPmoSummaryLedger:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def state(self, dedupe_key: str) -> str | None:
        return await run_sync(self._state, dedupe_key)

    def _state(self, dedupe_key: str) -> str | None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    "SELECT state FROM celerates_pmo_summaries WHERE dedupe_key = %s",
                    (dedupe_key,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="celerates_summary_get"
            ) from error
        return None if row is None else cast("str", row["state"])

    async def record(  # noqa: PLR0913, PLR0917
        self,
        dedupe_key: str,
        cycle_id: str,
        state: str,
        actor: str,
        provider_message_id: str | None,
        error: str | None,
    ) -> None:
        await run_sync(self._record, dedupe_key, cycle_id, state, actor, provider_message_id, error)

    def _record(  # noqa: PLR0913, PLR0917
        self,
        dedupe_key: str,
        cycle_id: str,
        state: str,
        actor: str,
        provider_message_id: str | None,
        error: str | None,
    ) -> None:
        try:
            with (
                _connect(self._dsn) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                _ = cursor.execute(
                    """
                    INSERT INTO celerates_pmo_summaries
                        (dedupe_key, cycle_id, state, actor, provider_message_id, last_error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (dedupe_key) DO UPDATE
                    SET state = EXCLUDED.state, actor = EXCLUDED.actor,
                        provider_message_id = EXCLUDED.provider_message_id,
                        last_error = EXCLUDED.last_error, created_at = now()
                    """,
                    (dedupe_key, cycle_id, state, actor, provider_message_id, error),
                )
        except psycopg.Error as err:
            raise InfrastructureError(
                service="postgres", operation="celerates_summary_put"
            ) from err
