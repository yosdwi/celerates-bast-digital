"""Attendance gap resolution requests with PMO approval.

Raw client attendance stays immutable. This table stores only a proposed value
for a missing punch, or an approved absence classification, plus the evidence
and audit metadata required to project CSV output without rewriting
attendance.check_in/check_out.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_0008"
down_revision: str | None = "20260825_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE attendance_resolution_requests (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            attendance_id       bigint NOT NULL
                REFERENCES attendance (id) ON DELETE CASCADE,
            evidence_id         uuid NOT NULL
                REFERENCES attendance_evidence (id) ON DELETE RESTRICT,
            employee_id         text NOT NULL
                REFERENCES employees (employee_id) ON UPDATE CASCADE,
            work_date           date NOT NULL,
            resolution_type     text NOT NULL
                CHECK (resolution_type IN (
                    'missing_clock_in',
                    'missing_clock_out',
                    'missing_both_worked',
                    'absence'
                )),
            absence_type        text
                CHECK (absence_type IS NULL OR absence_type IN ('cuti','izin','sakit')),
            proposed_check_in   time,
            proposed_check_out  time,
            status              text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected')),
            requested_by_jid    text NOT NULL,
            submitted_at        timestamptz NOT NULL DEFAULT now(),
            reviewed_by         text,
            reviewed_at         timestamptz,
            rejection_reason    text,
            CONSTRAINT ck_attendance_resolution_shape CHECK (
                (resolution_type = 'missing_clock_in'
                    AND proposed_check_in IS NOT NULL
                    AND proposed_check_out IS NULL
                    AND absence_type IS NULL)
                OR
                (resolution_type = 'missing_clock_out'
                    AND proposed_check_in IS NULL
                    AND proposed_check_out IS NOT NULL
                    AND absence_type IS NULL)
                OR
                (resolution_type = 'missing_both_worked'
                    AND proposed_check_in IS NOT NULL
                    AND proposed_check_out IS NOT NULL
                    AND absence_type IS NULL)
                OR
                (resolution_type = 'absence'
                    AND proposed_check_in IS NULL
                    AND proposed_check_out IS NULL
                    AND absence_type IS NOT NULL)
            ),
            CONSTRAINT ck_attendance_resolution_review CHECK (
                (status = 'pending'
                    AND reviewed_by IS NULL
                    AND reviewed_at IS NULL
                    AND rejection_reason IS NULL)
                OR
                (status = 'approved'
                    AND reviewed_by IS NOT NULL
                    AND reviewed_at IS NOT NULL
                    AND rejection_reason IS NULL)
                OR
                (status = 'rejected'
                    AND reviewed_by IS NOT NULL
                    AND reviewed_at IS NOT NULL
                    AND rejection_reason IS NOT NULL
                    AND btrim(rejection_reason) <> '')
            )
        );

        CREATE INDEX ix_attendance_resolution_status
            ON attendance_resolution_requests (status, submitted_at);
        CREATE INDEX ix_attendance_resolution_employee_date
            ON attendance_resolution_requests (employee_id, work_date);
        CREATE UNIQUE INDEX ux_attendance_resolution_open
            ON attendance_resolution_requests (attendance_id)
            WHERE status IN ('pending','approved');

        ALTER TABLE bot_conversations
            ADD COLUMN pending_attendance_resolution_type text
                CHECK (pending_attendance_resolution_type IS NULL OR
                       pending_attendance_resolution_type IN (
                           'missing_clock_in',
                           'missing_clock_out',
                           'missing_both_worked',
                           'absence'
                       )),
            ADD COLUMN pending_absence_type text
                CHECK (pending_absence_type IS NULL OR
                       pending_absence_type IN ('cuti','izin','sakit')),
            ADD COLUMN pending_proposed_check_in time,
            ADD COLUMN pending_proposed_check_out time;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nocodb_editor') THEN
                GRANT SELECT ON attendance_resolution_requests TO nocodb_editor;
            ELSE
                RAISE NOTICE
                    'role nocodb_editor is absent; skipping grant for attendance resolutions.';
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
                REVOKE ALL ON attendance_resolution_requests FROM nocodb_editor;
            END IF;
        END $$;

        ALTER TABLE bot_conversations
            DROP COLUMN pending_attendance_resolution_type,
            DROP COLUMN pending_absence_type,
            DROP COLUMN pending_proposed_check_in,
            DROP COLUMN pending_proposed_check_out;

        DROP TABLE attendance_resolution_requests;
        """
    )
