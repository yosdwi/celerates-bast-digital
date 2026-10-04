"""Add durable Payroll reminder delivery and response correlation to follow-ups."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0025"
down_revision: str | None = "20260919_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE talentops_followups
            ADD COLUMN delivery_state text,
            ADD COLUMN scope_key text,
            ADD COLUMN cycle_id text,
            ADD COLUMN milestone text,
            ADD COLUMN context_id uuid,
            ADD COLUMN reserved_at timestamptz,
            ADD COLUMN sending_at timestamptz,
            ADD COLUMN attempt_count integer NOT NULL DEFAULT 0,
            ADD COLUMN responded_at timestamptz,
            ADD COLUMN response_kind text;

        ALTER TABLE talentops_followups
            ADD CONSTRAINT ck_talentops_followups_delivery_state
                CHECK (
                    delivery_state IS NULL OR delivery_state IN (
                        'RESERVED',
                        'SENDING',
                        'SENT',
                        'FAILED_RETRYABLE',
                        'FAILED_FINAL',
                        'UNKNOWN'
                    )
                ),
            ADD CONSTRAINT ck_talentops_followups_attempt_count
                CHECK (attempt_count >= 0),
            ADD CONSTRAINT ck_talentops_followups_response_pair
                CHECK (
                    (responded_at IS NULL AND response_kind IS NULL)
                    OR (responded_at IS NOT NULL AND response_kind IS NOT NULL)
                );

        CREATE UNIQUE INDEX uq_talentops_followups_context_id
            ON talentops_followups (context_id)
            WHERE context_id IS NOT NULL;
        CREATE INDEX ix_talentops_followups_payroll_delivery
            ON talentops_followups (scope_key, cycle_id, milestone, delivery_state)
            WHERE delivery_state IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_talentops_followups_payroll_delivery;
        DROP INDEX IF EXISTS uq_talentops_followups_context_id;

        ALTER TABLE talentops_followups
            DROP CONSTRAINT IF EXISTS ck_talentops_followups_response_pair,
            DROP CONSTRAINT IF EXISTS ck_talentops_followups_attempt_count,
            DROP CONSTRAINT IF EXISTS ck_talentops_followups_delivery_state;

        ALTER TABLE talentops_followups
            DROP COLUMN IF EXISTS response_kind,
            DROP COLUMN IF EXISTS responded_at,
            DROP COLUMN IF EXISTS attempt_count,
            DROP COLUMN IF EXISTS sending_at,
            DROP COLUMN IF EXISTS reserved_at,
            DROP COLUMN IF EXISTS context_id,
            DROP COLUMN IF EXISTS milestone,
            DROP COLUMN IF EXISTS cycle_id,
            DROP COLUMN IF EXISTS scope_key,
            DROP COLUMN IF EXISTS delivery_state;
        """
    )
