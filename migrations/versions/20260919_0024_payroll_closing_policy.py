"""Add an independent Payroll closing reminder policy.

The legacy Talent/PMO calendar-day reminder fields remain untouched. Payroll
closing is opt-in and uses H-N offsets relative to its configured closing day.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0024"
down_revision: str | None = "20260919_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            ADD COLUMN payroll_closing_enabled boolean NOT NULL DEFAULT FALSE,
            ADD COLUMN payroll_closing_paused boolean NOT NULL DEFAULT FALSE,
            ADD COLUMN payroll_closing_day smallint NOT NULL DEFAULT 20,
            ADD COLUMN payroll_reminder_hour smallint NOT NULL DEFAULT 9,
            ADD COLUMN payroll_reminder_offsets smallint[] NOT NULL
                DEFAULT ARRAY[5,3,1]::smallint[],
            ADD COLUMN payroll_next_day_ready_hour smallint NOT NULL DEFAULT 6,
            ADD COLUMN payroll_policy_desired_version integer NOT NULL DEFAULT 1,
            ADD COLUMN payroll_policy_applied_version integer NOT NULL DEFAULT 0;

        ALTER TABLE workflow_notification_settings
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_closing_day
                CHECK (payroll_closing_day BETWEEN 1 AND 31),
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_reminder_hour
                CHECK (payroll_reminder_hour BETWEEN 0 AND 23),
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_ready_hour
                CHECK (payroll_next_day_ready_hour BETWEEN 0 AND 23),
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_offsets
                CHECK (cardinality(payroll_reminder_offsets) BETWEEN 1 AND 10),
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_desired_version
                CHECK (payroll_policy_desired_version > 0),
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_applied_version
                CHECK (
                    payroll_policy_applied_version >= 0
                    AND payroll_policy_applied_version <= payroll_policy_desired_version
                );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_applied_version,
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_desired_version,
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_offsets,
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_ready_hour,
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_reminder_hour,
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_closing_day;

        ALTER TABLE workflow_notification_settings
            DROP COLUMN IF EXISTS payroll_policy_applied_version,
            DROP COLUMN IF EXISTS payroll_policy_desired_version,
            DROP COLUMN IF EXISTS payroll_next_day_ready_hour,
            DROP COLUMN IF EXISTS payroll_reminder_offsets,
            DROP COLUMN IF EXISTS payroll_reminder_hour,
            DROP COLUMN IF EXISTS payroll_closing_day,
            DROP COLUMN IF EXISTS payroll_closing_paused,
            DROP COLUMN IF EXISTS payroll_closing_enabled;
        """
    )
