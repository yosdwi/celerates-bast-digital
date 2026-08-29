"""Allow repeated Task List evidence uploads.

Task evidence is talent-controlled: once a valid file is uploaded for a Closed
task, the evidence requirement is complete. Re-uploading the same bytes is not
a business error and must not create an additional validation workflow.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0011"
down_revision: str | None = "20260829_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_task_evidence_dedupe")


def downgrade() -> None:
    # A downgrade intentionally does not delete repeated uploads. If duplicate
    # rows were created after this migration, PostgreSQL will refuse to restore
    # the old unique index instead of silently discarding evidence.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_task_evidence_dedupe
            ON task_evidence (task_id, sha256)
        """
    )
