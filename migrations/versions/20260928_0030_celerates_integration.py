"""Celerates integration v1: command idempotency and governed reminder campaigns.

See docs/celerates-integration-v1.md. Campaign rows are the audience snapshot;
delivery state and every transition are audited. No readiness, correction or
export state is duplicated here -- those stay in their existing tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260928_0030"
down_revision: str | None = "20260922_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE celerates_idempotency (
            idempotency_key text NOT NULL,
            route           text NOT NULL,
            request_hash    text NOT NULL,
            status_code     integer NOT NULL,
            response        jsonb NOT NULL,
            actor           text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (idempotency_key, route),
            CONSTRAINT ck_celerates_idempotency_key
                CHECK (char_length(idempotency_key) BETWEEN 8 AND 160)
        );

        CREATE TABLE celerates_integration_control (
            scope_key   text PRIMARY KEY,
            kill_switch boolean NOT NULL DEFAULT false,
            updated_by  text,
            updated_at  timestamptz NOT NULL DEFAULT now()
        );
        INSERT INTO celerates_integration_control (scope_key) VALUES ('default');

        CREATE TABLE celerates_campaigns (
            id                   uuid PRIMARY KEY,
            scope_key            text NOT NULL DEFAULT 'default',
            kind                 text NOT NULL DEFAULT 'talent_attendance',
            cycle_id             text NOT NULL,
            cycle_year           integer NOT NULL,
            cycle_month          integer NOT NULL,
            state                text NOT NULL DEFAULT 'draft',
            window_start_hour    integer NOT NULL DEFAULT 8,
            window_end_hour      integer NOT NULL DEFAULT 18,
            batch_size           integer NOT NULL DEFAULT 10,
            cooldown_seconds     integer NOT NULL DEFAULT 600,
            min_interval_seconds integer NOT NULL DEFAULT 3,
            max_attempts         integer NOT NULL DEFAULT 3,
            next_dispatch_at     timestamptz,
            pause_reason         text,
            created_by           text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            approved_by          text,
            approved_at          timestamptz,
            finished_at          timestamptz,
            updated_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_celerates_campaign_kind CHECK (kind = 'talent_attendance'),
            CONSTRAINT ck_celerates_campaign_state
                CHECK (state IN ('draft', 'running', 'paused', 'completed', 'stopped')),
            CONSTRAINT ck_celerates_campaign_window
                CHECK (window_start_hour BETWEEN 0 AND 23
                       AND window_end_hour BETWEEN 1 AND 24
                       AND window_end_hour > window_start_hour),
            CONSTRAINT ck_celerates_campaign_bounds
                CHECK (batch_size BETWEEN 1 AND 50
                       AND cooldown_seconds BETWEEN 60 AND 86400
                       AND min_interval_seconds BETWEEN 0 AND 60
                       AND max_attempts BETWEEN 1 AND 5),
            CONSTRAINT ck_celerates_campaign_approval
                CHECK (state = 'draft' OR state = 'stopped' OR approved_by IS NOT NULL)
        );
        CREATE INDEX ix_celerates_campaigns_active
            ON celerates_campaigns (state, next_dispatch_at)
            WHERE state = 'running';

        CREATE TABLE celerates_campaign_recipients (
            id                  uuid PRIMARY KEY,
            campaign_id         uuid NOT NULL REFERENCES celerates_campaigns (id),
            employee_id         text NOT NULL,
            nrp                 text NOT NULL,
            name                text NOT NULL,
            eligibility         text NOT NULL,
            actionable_days     integer NOT NULL,
            blocker_fingerprint text NOT NULL,
            link_url            text,
            link_expires_at     timestamptz,
            state               text NOT NULL DEFAULT 'pending',
            attempt_count       integer NOT NULL DEFAULT 0,
            last_error          text,
            provider_message_id text,
            sent_at             timestamptz,
            updated_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_celerates_recipient UNIQUE (campaign_id, employee_id),
            CONSTRAINT ck_celerates_recipient_eligibility
                CHECK (eligibility IN ('eligible', 'not_bound')),
            CONSTRAINT ck_celerates_recipient_state
                CHECK (state IN ('pending', 'sending', 'sent', 'failed_retryable',
                                 'failed_final', 'unknown', 'skipped_resolved',
                                 'skipped_recent', 'skipped_link_expired',
                                 'skipped_no_account', 'skipped_not_bound',
                                 'skipped_stopped')),
            CONSTRAINT ck_celerates_recipient_link
                CHECK (link_url IS NULL OR link_expires_at IS NOT NULL)
        );
        CREATE INDEX ix_celerates_recipients_sent
            ON celerates_campaign_recipients (employee_id, sent_at)
            WHERE state = 'sent';

        CREATE TABLE celerates_campaign_events (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            campaign_id  uuid NOT NULL REFERENCES celerates_campaigns (id),
            recipient_id uuid REFERENCES celerates_campaign_recipients (id),
            event        text NOT NULL,
            actor        text NOT NULL,
            detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_celerates_campaign_events_campaign
            ON celerates_campaign_events (campaign_id, id);

        CREATE TABLE celerates_pmo_summaries (
            dedupe_key          text PRIMARY KEY,
            cycle_id            text NOT NULL,
            state               text NOT NULL,
            actor               text NOT NULL,
            provider_message_id text,
            last_error          text,
            created_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_celerates_pmo_summary_state
                CHECK (state IN ('sent', 'failed', 'unknown'))
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS celerates_pmo_summaries;
        DROP TABLE IF EXISTS celerates_campaign_events;
        DROP TABLE IF EXISTS celerates_campaign_recipients;
        DROP TABLE IF EXISTS celerates_campaigns;
        DROP TABLE IF EXISTS celerates_integration_control;
        DROP TABLE IF EXISTS celerates_idempotency;
        """
    )
