from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0002"
down_revision: str | None = "20260803_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE task_evidence (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            task_source   text NOT NULL,
            task_key      text NOT NULL,
            employee_id   text NOT NULL,
            work_date     date NOT NULL,
            caption       text NOT NULL DEFAULT '',
            content_type  text NOT NULL CHECK (content_type IN ('image/png','image/jpeg','image/webp')),
            byte_size     integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 5242880),
            sha256        text NOT NULL,
            image         bytea NOT NULL,
            uploaded_at   timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (task_source, task_key)
                REFERENCES durable_records (source, external_id) ON DELETE CASCADE
        );
        CREATE INDEX ix_task_evidence_task ON task_evidence (task_source, task_key);
        CREATE INDEX ix_task_evidence_employee_date ON task_evidence (employee_id, work_date);
        CREATE UNIQUE INDEX ux_task_evidence_dedupe ON task_evidence (task_source, task_key, sha256);

        CREATE TABLE wa_identity (
            wa_jid       text PRIMARY KEY,
            employee_id  text NOT NULL UNIQUE,
            bound_at     timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE activation_codes (
            employee_id      text PRIMARY KEY,
            code_hash        text NOT NULL,
            issued_at        timestamptz NOT NULL DEFAULT now(),
            used_at          timestamptz,
            failed_attempts  integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            locked_until     timestamptz
        );

        CREATE TABLE bot_conversations (
            wa_jid               text PRIMARY KEY,
            pending_task_source  text,
            pending_task_key     text,
            updated_at           timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (pending_task_source, pending_task_key)
                REFERENCES durable_records (source, external_id) ON DELETE CASCADE
        );

        CREATE TABLE bast_artifacts (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            report_type   text NOT NULL CHECK (report_type IN ('iotoperation','developer')),
            year          integer NOT NULL,
            month         integer NOT NULL CHECK (month BETWEEN 1 AND 12),
            fingerprint   text NOT NULL,
            document      text NOT NULL,
            generated_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_bast_artifacts_scope ON bast_artifacts (report_type, year, month, generated_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE bast_artifacts;
        DROP TABLE bot_conversations;
        DROP TABLE activation_codes;
        DROP TABLE wa_identity;
        DROP TABLE task_evidence;
        """
    )
