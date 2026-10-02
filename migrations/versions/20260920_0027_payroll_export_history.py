"""Add metadata-only history for Payroll attendance CSV exports."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0027"
down_revision: str | None = "20260920_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payroll_export_history (
            export_id       uuid PRIMARY KEY,
            cycle_id        text NOT NULL,
            cycle_label     text NOT NULL,
            start_date      date NOT NULL,
            end_date        date NOT NULL,
            exported_at     timestamptz NOT NULL,
            exported_by     text NOT NULL,
            report_type     text NOT NULL,
            role_filter     text NOT NULL,
            employee_filter text,
            filename        text NOT NULL,
            result          text NOT NULL,
            row_count       integer NOT NULL,
            CONSTRAINT ck_payroll_export_date_range
                CHECK (end_date >= start_date),
            CONSTRAINT ck_payroll_export_report_type
                CHECK (report_type IN ('developer', 'shifting')),
            CONSTRAINT ck_payroll_export_result
                CHECK (result IN ('SUCCESS')),
            CONSTRAINT ck_payroll_export_row_count
                CHECK (row_count >= 0),
            CONSTRAINT ck_payroll_export_filename_nonempty
                CHECK (length(btrim(filename)) > 0)
        );

        CREATE INDEX ix_payroll_export_history_cycle
            ON payroll_export_history (cycle_id, exported_at DESC);
        CREATE INDEX ix_payroll_export_history_exported_at
            ON payroll_export_history (exported_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE payroll_export_history")
