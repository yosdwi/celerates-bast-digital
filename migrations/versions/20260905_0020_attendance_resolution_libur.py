"""Add "libur" as a valid absence_type for attendance resolution requests.

PMO needs to correct a day where the source schedule sync (PAMA) wrongly
marked a shift on what was actually the talent's day off -- distinct from
Cuti/Izin/Sakit, which are approved leave, not a scheduling error.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0020"
down_revision: str | None = "20260904_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_resolution_requests
            DROP CONSTRAINT attendance_resolution_requests_absence_type_check;

        ALTER TABLE attendance_resolution_requests
            ADD CONSTRAINT attendance_resolution_requests_absence_type_check CHECK (
                absence_type IS NULL
                OR absence_type = ANY (ARRAY['cuti', 'izin', 'sakit', 'libur'])
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_resolution_requests
            DROP CONSTRAINT attendance_resolution_requests_absence_type_check;

        ALTER TABLE attendance_resolution_requests
            ADD CONSTRAINT attendance_resolution_requests_absence_type_check CHECK (
                absence_type IS NULL
                OR absence_type = ANY (ARRAY['cuti', 'izin', 'sakit'])
            );
        """
    )
