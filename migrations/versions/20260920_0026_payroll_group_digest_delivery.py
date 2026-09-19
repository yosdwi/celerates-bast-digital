"""Add durable delivery ledger for Payroll closing-group digests."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0026"
down_revision: str | None = "20260919_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payroll_group_digest_deliveries (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            idempotency_key     text NOT NULL UNIQUE,
            scope_key           text NOT NULL,
            cycle_id            text NOT NULL,
            milestone           text NOT NULL,
            group_jid           text NOT NULL,
            message             text NOT NULL,
            delivery_state      text NOT NULL DEFAULT 'RESERVED',
            attempt_count       integer NOT NULL DEFAULT 0,
            provider_message_id text,
            error_code          text,
            reserved_at         timestamptz NOT NULL DEFAULT now(),
            sending_at          timestamptz,
            sent_at             timestamptz,
            created_by          text NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_payroll_group_digest_group_jid
                CHECK (group_jid ~ '^[0-9]+(-[0-9]+)?@g[.]us$'),
            CONSTRAINT ck_payroll_group_digest_message_nonempty
                CHECK (length(btrim(message)) > 0),
            CONSTRAINT ck_payroll_group_digest_delivery_state
                CHECK (delivery_state IN (
                    'RESERVED',
                    'SENDING',
                    'SENT',
                    'FAILED_RETRYABLE',
                    'FAILED_FINAL',
                    'UNKNOWN'
                )),
            CONSTRAINT ck_payroll_group_digest_attempt_count
                CHECK (attempt_count >= 0)
        );

        CREATE UNIQUE INDEX uq_payroll_group_digest_scope_cycle_milestone
            ON payroll_group_digest_deliveries (scope_key, cycle_id, milestone);
        CREATE INDEX ix_payroll_group_digest_state
            ON payroll_group_digest_deliveries (delivery_state, reserved_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE payroll_group_digest_deliveries")
