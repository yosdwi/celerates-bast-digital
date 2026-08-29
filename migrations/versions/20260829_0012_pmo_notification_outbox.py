"""Durable PMO WhatsApp notification outbox.

Notification generation and delivery are intentionally separated. A unique
operator/dedupe key prevents duplicate digests or request notices when the
15-minute worker is retried, while delivery failures can be retried without
recreating business requests.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0012"
down_revision: str | None = "20260829_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workflow_notification_outbox (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operator_email       text NOT NULL
                REFERENCES workflow_operators(email) ON DELETE CASCADE,
            scope_key            text NOT NULL,
            kind                 text NOT NULL
                CHECK (kind IN ('attendance', 'rebind', 'digest')),
            dedupe_key           text NOT NULL,
            message              text NOT NULL,
            status               text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'sent', 'dead')),
            attempts             smallint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            next_attempt_at      timestamptz NOT NULL DEFAULT now(),
            provider_message_id  text,
            last_error           text,
            created_at           timestamptz NOT NULL DEFAULT now(),
            sent_at              timestamptz,
            UNIQUE (operator_email, dedupe_key)
        );

        CREATE INDEX ix_workflow_notification_outbox_due
            ON workflow_notification_outbox (next_attempt_at, created_at)
            WHERE status = 'pending';
        CREATE INDEX ix_workflow_notification_outbox_scope
            ON workflow_notification_outbox (scope_key, status, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_workflow_notification_outbox_scope;
        DROP INDEX IF EXISTS ix_workflow_notification_outbox_due;
        DROP TABLE IF EXISTS workflow_notification_outbox;
        """
    )
