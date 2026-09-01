"""Make PMO-issued Talent Mobile link validity configurable.

Manual Talent URLs are intentionally longer-lived than WhatsApp shortcut links,
but remain bounded. Existing workflow scopes default to seven days and Admin can
choose any value from one through seven days for newly generated PMO links.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0017"
down_revision: str | None = "20260901_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            ADD COLUMN talent_mobile_link_ttl_days integer NOT NULL DEFAULT 7,
            ADD CONSTRAINT ck_workflow_notification_settings_talent_mobile_link_ttl_days
                CHECK (talent_mobile_link_ttl_days BETWEEN 1 AND 7);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_talent_mobile_link_ttl_days,
            DROP COLUMN IF EXISTS talent_mobile_link_ttl_days;
        """
    )
