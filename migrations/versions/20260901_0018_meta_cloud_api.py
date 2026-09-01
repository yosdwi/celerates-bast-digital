"""Durable Meta Cloud API transport state and delivery lifecycle."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0018"
down_revision: str | None = "20260901_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE whatsapp_inbound_events (
            provider_message_id text PRIMARY KEY,
            wa_id               text NOT NULL,
            message_type        text NOT NULL,
            payload             jsonb NOT NULL,
            status              text NOT NULL
                CHECK (status IN ('queued', 'processing', 'processed', 'failed')),
            attempts            smallint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            last_error          text,
            received_at         timestamptz NOT NULL DEFAULT now(),
            processed_at        timestamptz,
            updated_at          timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_whatsapp_inbound_status_updated
            ON whatsapp_inbound_events (status, updated_at);

        CREATE TABLE whatsapp_outbound_requests (
            request_id          text PRIMARY KEY,
            payload_hash        text NOT NULL,
            status              text NOT NULL
                CHECK (status IN ('pending', 'sent', 'failed')),
            attempts            smallint NOT NULL DEFAULT 1 CHECK (attempts > 0),
            provider_message_id text,
            error_code          text,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            sent_at             timestamptz
        );

        CREATE INDEX ix_whatsapp_outbound_status_updated
            ON whatsapp_outbound_requests (status, updated_at);

        CREATE TABLE whatsapp_message_status_events (
            id                   bigserial PRIMARY KEY,
            provider_message_id  text NOT NULL,
            status               text NOT NULL,
            recipient_wa_id      text,
            provider_timestamp   text,
            error_code           text,
            error_title          text,
            received_at          timestamptz NOT NULL DEFAULT now(),
            UNIQUE (provider_message_id, status)
        );

        ALTER TABLE talentops_followups
            ADD COLUMN delivered_at timestamptz,
            ADD COLUMN read_at timestamptz,
            ADD COLUMN failed_at timestamptz,
            ADD COLUMN delivery_error_code text;

        ALTER TABLE workflow_notification_outbox
            ADD COLUMN delivered_at timestamptz,
            ADD COLUMN read_at timestamptz,
            ADD COLUMN failed_at timestamptz,
            ADD COLUMN delivery_error_code text;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_outbox
            DROP COLUMN IF EXISTS delivery_error_code,
            DROP COLUMN IF EXISTS failed_at,
            DROP COLUMN IF EXISTS read_at,
            DROP COLUMN IF EXISTS delivered_at;

        ALTER TABLE talentops_followups
            DROP COLUMN IF EXISTS delivery_error_code,
            DROP COLUMN IF EXISTS failed_at,
            DROP COLUMN IF EXISTS read_at,
            DROP COLUMN IF EXISTS delivered_at;

        DROP TABLE IF EXISTS whatsapp_message_status_events;
        DROP TABLE IF EXISTS whatsapp_outbound_requests;
        DROP TABLE IF EXISTS whatsapp_inbound_events;
        """
    )
