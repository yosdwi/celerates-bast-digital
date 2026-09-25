"""Add independent BAST closing campaign settings and evidence rules."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0028"
down_revision: str | None = "20260920_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bast_closing_settings (
            scope_key               text PRIMARY KEY,
            enabled                 boolean NOT NULL DEFAULT false,
            initial_day             smallint NOT NULL DEFAULT 25
                                      CHECK (initial_day BETWEEN 1 AND 31),
            followup_offsets        smallint[] NOT NULL
                                      DEFAULT ARRAY[3,1]::smallint[],
            send_hour               smallint NOT NULL DEFAULT 9
                                      CHECK (send_hour BETWEEN 0 AND 23),
            talent_reminder_enabled boolean NOT NULL DEFAULT true,
            pmo_summary_enabled     boolean NOT NULL DEFAULT true,
            pmo_group_jid           text,
            updated_by              text NOT NULL DEFAULT 'migration',
            updated_at              timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_bast_followup_offsets_nonnegative
                CHECK (0 <= ALL(followup_offsets))
        );

        CREATE TABLE bast_evidence_rules (
            scope_key         text NOT NULL,
            task_category     text NOT NULL,
            evidence_required boolean NOT NULL DEFAULT false,
            updated_by        text NOT NULL,
            updated_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (scope_key, task_category),
            CONSTRAINT ck_bast_evidence_category_nonempty
                CHECK (length(btrim(task_category)) > 0)
        );

        CREATE INDEX ix_bast_evidence_rules_scope
            ON bast_evidence_rules (scope_key);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS bast_evidence_rules;
        DROP TABLE IF EXISTS bast_closing_settings;
        """
    )
