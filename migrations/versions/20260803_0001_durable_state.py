from collections.abc import Sequence

from alembic import op

revision: str = "20260803_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE durable_records (
            source text NOT NULL,
            external_id text NOT NULL,
            entity_kind text NOT NULL CHECK (
                entity_kind IN ('holiday', 'attendance', 'task', 'schedule', 'timesheet')
            ),
            work_date date NOT NULL,
            payload jsonb NOT NULL,
            source_updated_at timestamptz,
            version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (source, external_id)
        );
        CREATE INDEX ix_durable_records_kind_date ON durable_records (entity_kind, work_date);
        CREATE TABLE sync_watermarks (
            source_key text PRIMARY KEY,
            cursor_value text NOT NULL,
            watermark timestamptz NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE manual_record_locks (
            record_key text PRIMARY KEY,
            owner_id text NOT NULL,
            acquired_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            CHECK (expires_at > acquired_at)
        );
        CREATE INDEX ix_manual_record_locks_expires_at ON manual_record_locks (expires_at);
        CREATE TABLE flow_runs (
            id uuid PRIMARY KEY,
            flow_name text NOT NULL,
            status text NOT NULL CHECK (
                status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')
            ),
            parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
            result jsonb,
            error_code text,
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (finished_at IS NULL OR started_at IS NOT NULL)
        );
        CREATE INDEX ix_flow_runs_flow_created_at ON flow_runs (flow_name, created_at DESC);
        CREATE TABLE generation_plans (
            id uuid PRIMARY KEY,
            owner_id text NOT NULL,
            status text NOT NULL CHECK (
                status IN ('draft', 'running', 'completed', 'failed', 'expired')
            ),
            plan jsonb NOT NULL,
            retention_until timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_generation_plans_retention ON generation_plans (retention_until);
        CREATE TABLE retention_runs (
            id uuid PRIMARY KEY,
            cutoff_at timestamptz NOT NULL,
            status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
            deleted_count bigint NOT NULL DEFAULT 0 CHECK (deleted_count >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE retention_runs;
        DROP TABLE generation_plans;
        DROP TABLE flow_runs;
        DROP TABLE manual_record_locks;
        DROP TABLE sync_watermarks;
        DROP TABLE durable_records;
        """
    )
