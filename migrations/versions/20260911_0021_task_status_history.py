"""Record task status transitions so PMO can see where a task sat longest.

The Redmine sync overwrites `tasks.status` in place every 15 minutes
(operational-import), so the previous status is lost on every write. Since
there is no Redmine journal/history feed wired into the warehouse view this
app reads from, the only way to get a transition timeline is to build one
ourselves: log an event whenever the pipeline's upsert actually changes
`status`. History starts accumulating from whenever this migration ships --
transitions that already happened before that are not recoverable.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0021"
down_revision: str | None = "20260905_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE task_status_history (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            record_key  text NOT NULL
                REFERENCES tasks (record_key) ON DELETE CASCADE,
            old_status  text,
            new_status  text NOT NULL,
            changed_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_task_status_history_record_key
            ON task_status_history (record_key, changed_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE task_status_history;")
