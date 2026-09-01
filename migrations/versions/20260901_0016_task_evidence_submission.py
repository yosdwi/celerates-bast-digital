"""Stage Task Evidence until Talent explicitly submits it to PMO.

Existing evidence predates the PMO guideline submit step and is grandfathered as
already submitted. New legacy WhatsApp uploads keep the historical immediate
submission behaviour through the column default, while Talent Mobile may write
an explicit NULL submitted_at and activate it only from the final "Ajukan ke
PMO" action.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0016"
down_revision: str | None = "20260901_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE task_evidence
            ADD COLUMN submitted_at timestamptz,
            ADD COLUMN submitted_by_jid text;

        UPDATE task_evidence
        SET submitted_at = uploaded_at
        WHERE submitted_at IS NULL;

        ALTER TABLE task_evidence
            ALTER COLUMN submitted_at SET DEFAULT now();

        CREATE INDEX ix_task_evidence_staged_employee_date
            ON task_evidence (employee_id, work_date)
            WHERE submitted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_task_evidence_staged_employee_date;
        ALTER TABLE task_evidence
            DROP COLUMN IF EXISTS submitted_by_jid,
            DROP COLUMN IF EXISTS submitted_at;
        """
    )
