"""Typed business tables replacing the durable_records jsonb blob.

NocoDB cannot UPDATE or DELETE a relation without a single-column primary key,
and durable_records has a composite PK with every business field buried in a
jsonb payload. Since NocoDB and the WhatsApp bot must edit the *same* rows (one
store, no sync), the business entities need real tables with a surrogate id.

Manual-edit protection moves from NocoDB's updated_by/IsManualEdit pair to a
single mechanism: the app connects as digital_bast_app, NocoDB connects as
nocodb_editor, so mark_manual_edit() flips origin to 'manual' for any write
that did not come from the pipeline. The pipeline's upsert then carries
`WHERE origin <> 'manual'`, matching what repositories.py already did with
payload->>'origin'.

record_key deliberately carries the existing RecordKey strings so
domain/identity.py is reused unchanged.

durable_records is left in place and unused; dropping it is a separate
migration once a full month has been verified against the new tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_0004"
down_revision: str | None = "20260819_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION mark_manual_edit() RETURNS trigger AS $$
        BEGIN
            IF current_user <> 'digital_bast_app' THEN
                NEW.origin := 'manual';
            END IF;
            NEW.updated_at := now();
            NEW.version := COALESCE(OLD.version, 0) + 1;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TABLE employees (
            id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            employee_id        text NOT NULL UNIQUE,
            nrp                text NOT NULL UNIQUE,
            full_name          text NOT NULL,
            role               text NOT NULL
                CHECK (role IN ('Developer','IoT Operations')),
            status             text NOT NULL DEFAULT 'Active',
            grade              text NOT NULL DEFAULT '',
            join_date          date,
            notification_email text NOT NULL DEFAULT '',
            origin             text NOT NULL DEFAULT 'pipeline'
                CHECK (origin IN ('pipeline','manual')),
            version            bigint NOT NULL DEFAULT 1,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE holidays (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            record_key  text NOT NULL UNIQUE,
            work_date   date NOT NULL UNIQUE,
            name        text NOT NULL,
            origin      text NOT NULL DEFAULT 'pipeline'
                CHECK (origin IN ('pipeline','manual')),
            version     bigint NOT NULL DEFAULT 1,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE schedules (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            record_key  text NOT NULL UNIQUE,
            employee_id text NOT NULL
                REFERENCES employees (employee_id) ON UPDATE CASCADE,
            work_date   date NOT NULL,
            shift_name  text NOT NULL DEFAULT '',
            origin      text NOT NULL DEFAULT 'pipeline'
                CHECK (origin IN ('pipeline','manual')),
            version     bigint NOT NULL DEFAULT 1,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (employee_id, work_date)
        );

        CREATE TABLE attendance (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            record_key      text NOT NULL UNIQUE,
            employee_id     text NOT NULL
                REFERENCES employees (employee_id) ON UPDATE CASCADE,
            work_date       date NOT NULL,
            shift           text NOT NULL DEFAULT '',
            schedule_in     text NOT NULL DEFAULT '',
            schedule_out    text NOT NULL DEFAULT '',
            attendance_code text NOT NULL DEFAULT '',
            check_in        time,
            check_out       time,
            notes           text NOT NULL DEFAULT '',
            evidence_note   text NOT NULL DEFAULT '',
            origin          text NOT NULL DEFAULT 'pipeline'
                CHECK (origin IN ('pipeline','manual')),
            version         bigint NOT NULL DEFAULT 1,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (employee_id, work_date)
        );
        CREATE INDEX ix_attendance_work_date ON attendance (work_date);

        CREATE TABLE tasks (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            record_key   text NOT NULL UNIQUE,
            employee_id  text NOT NULL
                REFERENCES employees (employee_id) ON UPDATE CASCADE,
            work_date    date NOT NULL,
            title        text NOT NULL,
            requestor    text NOT NULL DEFAULT '',
            status       text NOT NULL DEFAULT '',
            category     text NOT NULL,
            task_source  text NOT NULL
                CHECK (task_source IN ('redmine','google_sheet')),
            source_id    text NOT NULL,
            assignee     text NOT NULL DEFAULT '',
            start_at     timestamptz,
            response_at  timestamptz,
            close_at     timestamptz,
            end_date     date,
            achievement  integer NOT NULL DEFAULT 0
                CHECK (achievement BETWEEN 0 AND 100),
            issue_type   text NOT NULL DEFAULT '',
            origin       text NOT NULL DEFAULT 'pipeline'
                CHECK (origin IN ('pipeline','manual')),
            version      bigint NOT NULL DEFAULT 1,
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tasks_employee_date ON tasks (employee_id, work_date);
        CREATE INDEX ix_tasks_date ON tasks (work_date);

        CREATE TABLE timesheets (
            id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            record_key     text NOT NULL UNIQUE,
            employee_id    text NOT NULL
                REFERENCES employees (employee_id) ON UPDATE CASCADE,
            work_date      date NOT NULL,
            calendar_month text NOT NULL DEFAULT '',
            activity       text NOT NULL DEFAULT '',
            project        text NOT NULL DEFAULT '',
            is_holiday     boolean NOT NULL DEFAULT false,
            remarks        text NOT NULL DEFAULT '',
            origin         text NOT NULL DEFAULT 'pipeline'
                CHECK (origin IN ('pipeline','manual')),
            version        bigint NOT NULL DEFAULT 1,
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (employee_id, work_date)
        );
        CREATE INDEX ix_timesheets_date ON timesheets (work_date);

        CREATE TRIGGER trg_manual_edit BEFORE UPDATE ON employees
            FOR EACH ROW EXECUTE FUNCTION mark_manual_edit();
        CREATE TRIGGER trg_manual_edit BEFORE UPDATE ON holidays
            FOR EACH ROW EXECUTE FUNCTION mark_manual_edit();
        CREATE TRIGGER trg_manual_edit BEFORE UPDATE ON schedules
            FOR EACH ROW EXECUTE FUNCTION mark_manual_edit();
        CREATE TRIGGER trg_manual_edit BEFORE UPDATE ON attendance
            FOR EACH ROW EXECUTE FUNCTION mark_manual_edit();
        CREATE TRIGGER trg_manual_edit BEFORE UPDATE ON tasks
            FOR EACH ROW EXECUTE FUNCTION mark_manual_edit();
        CREATE TRIGGER trg_manual_edit BEFORE UPDATE ON timesheets
            FOR EACH ROW EXECUTE FUNCTION mark_manual_edit();
        """
    )

    # The 0002 foreign keys are unnamed, so Postgres auto-generated names that
    # may have been truncated to 63 characters. Look them up rather than
    # guessing the spelling.
    op.execute(
        """
        DO $$
        DECLARE
            constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'task_evidence'::regclass
                  AND confrelid = 'durable_records'::regclass
            LOOP
                EXECUTE format(
                    'ALTER TABLE task_evidence DROP CONSTRAINT %I', constraint_name
                );
            END LOOP;
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'bot_conversations'::regclass
                  AND confrelid = 'durable_records'::regclass
            LOOP
                EXECUTE format(
                    'ALTER TABLE bot_conversations DROP CONSTRAINT %I', constraint_name
                );
            END LOOP;
        END $$;
        """
    )

    # task_evidence and bot_conversations carry no rows worth preserving: the
    # WhatsApp evidence flow has never run against a database that had them
    # (the VPS is still on 20260803_0001), so there is nothing to backfill.
    op.execute(
        """
        DELETE FROM task_evidence;
        DELETE FROM bot_conversations;

        DROP INDEX ux_task_evidence_dedupe;
        DROP INDEX ix_task_evidence_task;
        ALTER TABLE task_evidence
            DROP COLUMN task_source,
            DROP COLUMN task_key,
            ADD COLUMN task_id bigint NOT NULL
                REFERENCES tasks (id) ON DELETE CASCADE;
        CREATE INDEX ix_task_evidence_task ON task_evidence (task_id);
        CREATE UNIQUE INDEX ux_task_evidence_dedupe
            ON task_evidence (task_id, sha256);

        ALTER TABLE bot_conversations
            DROP COLUMN pending_task_source,
            DROP COLUMN pending_task_key,
            ADD COLUMN pending_task_id bigint
                REFERENCES tasks (id) ON DELETE CASCADE;
        """
    )

    # Least-privilege login for nocodb-v2. The password is set out of band by
    # the deploy runbook so no secret ever lands in a migration file.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nocodb_editor') THEN
                CREATE ROLE nocodb_editor LOGIN;
            END IF;
        END $$;

        GRANT USAGE ON SCHEMA public TO nocodb_editor;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON employees, holidays, schedules, attendance, tasks, timesheets
            TO nocodb_editor;
        GRANT SELECT ON task_evidence TO nocodb_editor;
        GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nocodb_editor;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL ON task_evidence FROM nocodb_editor;
        REVOKE ALL ON employees, holidays, schedules, attendance, tasks, timesheets
            FROM nocodb_editor;
        REVOKE USAGE ON SCHEMA public FROM nocodb_editor;

        DELETE FROM task_evidence;
        DELETE FROM bot_conversations;

        DROP INDEX ux_task_evidence_dedupe;
        DROP INDEX ix_task_evidence_task;
        ALTER TABLE task_evidence
            DROP COLUMN task_id,
            ADD COLUMN task_source text NOT NULL,
            ADD COLUMN task_key text NOT NULL,
            ADD FOREIGN KEY (task_source, task_key)
                REFERENCES durable_records (source, external_id) ON DELETE CASCADE;
        CREATE INDEX ix_task_evidence_task ON task_evidence (task_source, task_key);
        CREATE UNIQUE INDEX ux_task_evidence_dedupe
            ON task_evidence (task_source, task_key, sha256);

        ALTER TABLE bot_conversations
            DROP COLUMN pending_task_id,
            ADD COLUMN pending_task_source text,
            ADD COLUMN pending_task_key text,
            ADD FOREIGN KEY (pending_task_source, pending_task_key)
                REFERENCES durable_records (source, external_id) ON DELETE CASCADE;

        DROP TABLE timesheets;
        DROP TABLE tasks;
        DROP TABLE attendance;
        DROP TABLE schedules;
        DROP TABLE holidays;
        DROP TABLE employees;
        DROP FUNCTION mark_manual_edit();
        """
    )
