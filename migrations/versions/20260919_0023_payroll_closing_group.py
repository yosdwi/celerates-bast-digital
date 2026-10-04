"""Add the allowed WhatsApp group for Payroll closing operations."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0023"
down_revision: str | None = "20260919_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            ADD COLUMN payroll_closing_group_jid text;

        ALTER TABLE workflow_notification_settings
            ADD CONSTRAINT ck_workflow_notification_settings_payroll_group_jid
            CHECK (
                payroll_closing_group_jid IS NULL
                OR payroll_closing_group_jid ~ '^[0-9]+(-[0-9]+)?@g\\.us$'
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_notification_settings
            DROP CONSTRAINT IF EXISTS ck_workflow_notification_settings_payroll_group_jid;
        ALTER TABLE workflow_notification_settings
            DROP COLUMN IF EXISTS payroll_closing_group_jid;
        """
    )
