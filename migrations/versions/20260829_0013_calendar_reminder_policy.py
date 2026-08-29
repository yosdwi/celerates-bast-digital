"""Separate Talent and PMO reminder dates by calendar day.

The previous notification settings carried a generic deadline-offset field and
a daily-digest switch. Business policy is simpler: Admin chooses explicit
calendar dates in each month for Talent reminders and PMO reminders. Existing
immediate PMO alerts remain independent opt-in notifications.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0013"
down_revision: str | None = "20260829_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            ADD COLUMN reminder_hour smallint NOT NULL DEFAULT 9
                CHECK (reminder_hour BETWEEN 0 AND 23),
            ADD COLUMN talent_reminder_days smallint[] NOT NULL
                DEFAULT ARRAY[]::smallint[],
            ADD COLUMN pmo_reminder_days smallint[] NOT NULL
                DEFAULT ARRAY[]::smallint[];

        UPDATE workflow_notification_settings
        SET reminder_hour = digest_hour;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            DROP COLUMN IF EXISTS pmo_reminder_days,
            DROP COLUMN IF EXISTS talent_reminder_days,
            DROP COLUMN IF EXISTS reminder_hour;
        """
    )
