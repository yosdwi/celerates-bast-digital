"""Persist short-lived Talent WhatsApp intent/period context.

This context is deliberately separate from bot_conversations.updated_at, which
owns the legacy 15-minute evidence-selection TTL. Natural-language navigation
must not accidentally keep an old evidence/task selection alive. Business
state remains authoritative in the domain tables; these columns only remember
which Talent surface/period a conversational follow-up refers to.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0015"
down_revision: str | None = "20260901_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_conversations
            ADD COLUMN talent_context_intent text
                CHECK (talent_context_intent IN ('home','attendance','tasks','status','requests')),
            ADD COLUMN talent_context_start_date date,
            ADD COLUMN talent_context_end_date date,
            ADD COLUMN talent_context_updated_at timestamptz;

        ALTER TABLE bot_conversations
            ADD CONSTRAINT ck_bot_conversations_talent_context_dates
            CHECK (
                (talent_context_intent IS NULL
                    AND talent_context_start_date IS NULL
                    AND talent_context_end_date IS NULL
                    AND talent_context_updated_at IS NULL)
                OR
                (talent_context_intent IS NOT NULL
                    AND talent_context_start_date IS NOT NULL
                    AND talent_context_end_date IS NOT NULL
                    AND talent_context_updated_at IS NOT NULL
                    AND talent_context_end_date >= talent_context_start_date)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_conversations
            DROP CONSTRAINT IF EXISTS ck_bot_conversations_talent_context_dates,
            DROP COLUMN IF EXISTS talent_context_updated_at,
            DROP COLUMN IF EXISTS talent_context_end_date,
            DROP COLUMN IF EXISTS talent_context_start_date,
            DROP COLUMN IF EXISTS talent_context_intent;
        """
    )
