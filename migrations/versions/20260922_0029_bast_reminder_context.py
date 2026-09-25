"""Add durable context for BAST closing reminder replies."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0029"
down_revision: str | None = "20260922_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bast_reminder_contexts (
            wa_jid       text PRIMARY KEY,
            employee_id text NOT NULL,
            period_start date NOT NULL,
            period_end   date NOT NULL,
            domains      text[] NOT NULL,
            expires_at   timestamptz NOT NULL,
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_bast_reminder_period
                CHECK (period_end >= period_start),
            CONSTRAINT ck_bast_reminder_domains
                CHECK (cardinality(domains) > 0)
        );

        CREATE INDEX ix_bast_reminder_context_employee
            ON bast_reminder_contexts (employee_id);
        CREATE INDEX ix_bast_reminder_context_expiry
            ON bast_reminder_contexts (expires_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bast_reminder_contexts;")
