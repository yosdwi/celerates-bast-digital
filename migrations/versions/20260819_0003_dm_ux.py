from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0003"
down_revision: str | None = "20260819_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        -- NRP-based DM onboarding: a claimed-but-unconfirmed employee_id,
        -- reusing bot_conversations' existing 15-minute updated_at TTL window.
        ALTER TABLE bot_conversations ADD COLUMN pending_employee_id text;

        -- Photo-arrives-before-task-is-unambiguous draft (§5): the raw image
        -- is retained here, scoped to the sender, until the next reply picks
        -- a candidate or the row ages out of the same TTL window.
        ALTER TABLE bot_conversations ADD COLUMN pending_image bytea;
        ALTER TABLE bot_conversations ADD COLUMN pending_image_content_type text;
        ALTER TABLE bot_conversations ADD COLUMN pending_image_caption text;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_conversations DROP COLUMN pending_image_caption;
        ALTER TABLE bot_conversations DROP COLUMN pending_image_content_type;
        ALTER TABLE bot_conversations DROP COLUMN pending_image;
        ALTER TABLE bot_conversations DROP COLUMN pending_employee_id;
        """
    )
