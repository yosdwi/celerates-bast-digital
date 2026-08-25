"""attendance_evidence table + bot_conversations.pending_attendance_id.

WhatsApp DM evidence upload has only ever covered Closed tasks (task_evidence,
see 20260819_0002_bast_evidence.py). Attendance's "has evidence" signal has
been a manually-typed NocoDB text column (attendance.evidence_note) with no
talent-facing upload path -- this adds the same photo-upload table for
Attendance that task_evidence already provides for Task List, mirroring its
post-typed-tables shape exactly (uuid PK, FK to the typed parent row's bigint
id, same content-type/size checks, same sha256 per-parent dedupe index).

pending_attendance_id mirrors bot_conversations.pending_task_id (added in
20260820_0004_typed_tables.py) so the DM "waiting for a photo" state can track
either target -- src/digital_bast/bot/attendance_evidence.py's
set_pending_attendance always clears pending_task_id in the same UPDATE (and
vice versa), so the two are mutually exclusive at the application layer; only
one can be a real, resolvable target at a time regardless.

pending_evidence_kind is a lighter-weight marker than either pending id: it
records which *list* ("task" or "attendance") the bot most recently showed,
so a bare number reply ("1") that arrives before a specific pick is made
resolves against the right one -- two independently-numbered lists exist now,
so a bare index is otherwise ambiguous whenever both have outstanding items.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE attendance_evidence (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            attendance_id bigint NOT NULL
                REFERENCES attendance (id) ON DELETE CASCADE,
            employee_id   text NOT NULL,
            work_date     date NOT NULL,
            caption       text NOT NULL DEFAULT '',
            content_type  text NOT NULL
                CHECK (content_type IN ('image/png','image/jpeg','image/webp')),
            byte_size     integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 5242880),
            sha256        text NOT NULL,
            image         bytea NOT NULL,
            uploaded_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_attendance_evidence_attendance ON attendance_evidence (attendance_id);
        CREATE UNIQUE INDEX ux_attendance_evidence_dedupe
            ON attendance_evidence (attendance_id, sha256);

        ALTER TABLE bot_conversations
            ADD COLUMN pending_attendance_id bigint
                REFERENCES attendance (id) ON DELETE CASCADE,
            ADD COLUMN pending_evidence_kind text
                CHECK (pending_evidence_kind IN ('task', 'attendance'));
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nocodb_editor') THEN
                GRANT SELECT ON attendance_evidence TO nocodb_editor;
            ELSE
                RAISE NOTICE
                    'role nocodb_editor is absent; skipping grant. '
                    'Create it as the superuser to give nocodb-v2 access.';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nocodb_editor') THEN
                REVOKE ALL ON attendance_evidence FROM nocodb_editor;
            END IF;
        END $$;

        ALTER TABLE bot_conversations
            DROP COLUMN pending_attendance_id,
            DROP COLUMN pending_evidence_kind;
        DROP TABLE attendance_evidence;
        """
    )
