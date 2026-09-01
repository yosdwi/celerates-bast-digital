"""Stage Task Evidence until Talent explicitly submits it to PMO.

The PMO guideline separates attaching evidence from the final "Ajukan ke PMO"
action. Draft files therefore live in a staging table and cannot accidentally
satisfy readiness/Generator BAST. Submission moves them transactionally into
task_evidence. Existing and legacy WhatsApp evidence remains immediately
submitted and is grandfathered with submitted_at=uploaded_at.
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

        CREATE TABLE task_evidence_staged (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            task_id      bigint NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
            employee_id  text NOT NULL,
            work_date    date NOT NULL,
            caption      text NOT NULL DEFAULT '',
            content_type text NOT NULL
                CHECK (content_type IN ('image/png','image/jpeg','image/webp')),
            byte_size    integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 5242880),
            sha256       text NOT NULL,
            image        bytea NOT NULL,
            staged_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_task_evidence_staged_task
            ON task_evidence_staged (task_id);
        CREATE INDEX ix_task_evidence_staged_employee_date
            ON task_evidence_staged (employee_id, work_date);
        CREATE UNIQUE INDEX ux_task_evidence_staged_dedupe
            ON task_evidence_staged (task_id, sha256);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS task_evidence_staged;
        ALTER TABLE task_evidence
            DROP COLUMN IF EXISTS submitted_by_jid,
            DROP COLUMN IF EXISTS submitted_at;
        """
    )
