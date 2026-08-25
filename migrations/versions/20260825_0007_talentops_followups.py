"""Persist TalentOps outbound follow-up audit records."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0007"
down_revision: str | None = "20260825_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE talentops_followups (
            id                  text PRIMARY KEY,
            idempotency_key     text NOT NULL UNIQUE,
            employee_id         text NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            period_start        date NOT NULL,
            period_end          date NOT NULL,
            channel             text NOT NULL DEFAULT 'whatsapp',
            message             text NOT NULL,
            source              text NOT NULL,
            status              text NOT NULL,
            provider_message_id text,
            created_by          text NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            sent_at             timestamptz,
            error_code          text,
            CONSTRAINT talentops_followups_period_order CHECK (period_end >= period_start),
            CONSTRAINT talentops_followups_message_nonempty CHECK (length(btrim(message)) > 0)
        );

        CREATE INDEX ix_talentops_followups_employee_created
            ON talentops_followups (employee_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE talentops_followups")
