"""Persist the Talent mobile public origin in the workflow control plane.

The environment variable remains a bootstrap/backward-compatible fallback, but
Admin can manage the active public origin from TalentOps Web without editing
server environment files.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0014"
down_revision: str | None = "20260829_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            ADD COLUMN talent_mobile_public_url text;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            DROP COLUMN IF EXISTS talent_mobile_public_url;
        """
    )
