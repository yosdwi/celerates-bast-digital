"""Celerates integration v1 additions: direct messages, links without expiry, task counts.

See docs/celerates-integration-v1.md. A PMO "Kirim pengingat" is one audited
row in celerates_direct_messages. Campaign links may carry no expiry (Celerates
enforces single use), so the recipient link/expiry pairing constraint goes.
Recipients also record how many tasks without evidence were open.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260929_0031"
down_revision: str | None = "20260928_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE celerates_direct_messages (
            id                  uuid PRIMARY KEY,
            employee_id         text NOT NULL,
            cycle_id            text NOT NULL,
            cycle_year          integer NOT NULL,
            cycle_month         integer NOT NULL,
            actor               text NOT NULL,
            link_url            text NOT NULL,
            link_expires_at     timestamptz,
            attendance_days     integer NOT NULL DEFAULT 0,
            missing_tasks       integer NOT NULL DEFAULT 0,
            status              text NOT NULL DEFAULT 'sending',
            provider_message_id text,
            last_error          text,
            created_at          timestamptz NOT NULL DEFAULT now(),
            sent_at             timestamptz,
            updated_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_celerates_direct_status
                CHECK (status IN ('sending', 'sent', 'failed', 'unknown')),
            CONSTRAINT ck_celerates_direct_sent
                CHECK (status <> 'sent' OR sent_at IS NOT NULL),
            CONSTRAINT ck_celerates_direct_counts
                CHECK (attendance_days >= 0 AND missing_tasks >= 0)
        );
        CREATE INDEX ix_celerates_direct_employee
            ON celerates_direct_messages (employee_id, created_at);
        CREATE INDEX ix_celerates_direct_sent
            ON celerates_direct_messages (employee_id, sent_at)
            WHERE status = 'sent';

        ALTER TABLE celerates_campaign_recipients
            DROP CONSTRAINT ck_celerates_recipient_link;
        ALTER TABLE celerates_campaign_recipients
            ADD COLUMN missing_tasks integer NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    # NOT VALID: rows approved with a never-expiring link stay; new rows are checked.
    op.execute(
        """
        ALTER TABLE celerates_campaign_recipients DROP COLUMN IF EXISTS missing_tasks;
        ALTER TABLE celerates_campaign_recipients
            ADD CONSTRAINT ck_celerates_recipient_link
                CHECK (link_url IS NULL OR link_expires_at IS NOT NULL) NOT VALID;
        DROP TABLE IF EXISTS celerates_direct_messages;
        """
    )
