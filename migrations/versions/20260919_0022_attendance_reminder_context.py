"""Add stable Payroll attendance reminder snapshots to bot conversations.

The existing ``talent_context_*`` columns remember only short-lived navigation
intent and period. Payroll reminder replies need a different guarantee: the
number/order shown to a Talent must continue to refer to the exact attendance
identities that were sent, even if the live closing projection changes later.

These columns store identity/context only. They intentionally do not persist
Payroll readiness or any other business decision.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0022"
down_revision: str | None = "20260911_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_conversations
            ADD COLUMN attendance_context_id uuid,
            ADD COLUMN attendance_context_version integer,
            ADD COLUMN attendance_context_employee_id text,
            ADD COLUMN attendance_context_cycle_id text,
            ADD COLUMN attendance_context_keys jsonb,
            ADD COLUMN attendance_context_expires_at timestamptz;

        ALTER TABLE bot_conversations
            ADD CONSTRAINT ck_bot_conversations_attendance_context_complete
            CHECK (
                (attendance_context_id IS NULL
                    AND attendance_context_version IS NULL
                    AND attendance_context_employee_id IS NULL
                    AND attendance_context_cycle_id IS NULL
                    AND attendance_context_keys IS NULL
                    AND attendance_context_expires_at IS NULL)
                OR
                (attendance_context_id IS NOT NULL
                    AND attendance_context_version IS NOT NULL
                    AND attendance_context_version > 0
                    AND NULLIF(btrim(attendance_context_employee_id), '') IS NOT NULL
                    AND NULLIF(btrim(attendance_context_cycle_id), '') IS NOT NULL
                    AND attendance_context_keys IS NOT NULL
                    AND jsonb_typeof(attendance_context_keys) = 'array'
                    AND jsonb_array_length(attendance_context_keys) BETWEEN 1 AND 64
                    AND attendance_context_expires_at IS NOT NULL)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_conversations
            DROP CONSTRAINT IF EXISTS ck_bot_conversations_attendance_context_complete,
            DROP COLUMN IF EXISTS attendance_context_expires_at,
            DROP COLUMN IF EXISTS attendance_context_keys,
            DROP COLUMN IF EXISTS attendance_context_cycle_id,
            DROP COLUMN IF EXISTS attendance_context_employee_id,
            DROP COLUMN IF EXISTS attendance_context_version,
            DROP COLUMN IF EXISTS attendance_context_id;
        """
    )
