"""Allow optional proposed clock in/out on an absence resolution request.

Sakit/Izin/Cuti previously forced proposed_check_in/out to NULL. A talent on
an absence day may still have a partial punch worth recording, so the shape
constraint now only requires absence_type to be set; the clock fields become
optional (not mandatory) rather than forbidden.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0019"
down_revision: str | None = "20260902_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_resolution_requests
            DROP CONSTRAINT ck_attendance_resolution_shape;

        ALTER TABLE attendance_resolution_requests
            ADD CONSTRAINT ck_attendance_resolution_shape CHECK (
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
                    AND absence_type IS NOT NULL)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_resolution_requests
            DROP CONSTRAINT ck_attendance_resolution_shape;

        ALTER TABLE attendance_resolution_requests
            ADD CONSTRAINT ck_attendance_resolution_shape CHECK (
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
            );
        """
    )
