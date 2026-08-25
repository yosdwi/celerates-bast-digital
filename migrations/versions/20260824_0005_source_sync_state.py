"""Persist last successful server ingest per bridge source."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260824_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE source_sync_state (
            source_key      text PRIMARY KEY,
            last_success_at timestamptz NOT NULL,
            updated_at      timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE source_sync_state")
