"""Mark new attendance evidence as requiring PMO resolution approval.

The default is deliberately false so every row that existed before this
migration remains valid under the historical readiness contract. The WhatsApp
attendance upload service explicitly writes true for new rows. Readiness can
therefore require an approved resolution for new bot evidence without making
old production evidence regress overnight.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0009"
down_revision: str | None = "20260828_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "attendance_evidence",
        sa.Column(
            "requires_resolution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("attendance_evidence", "requires_resolution")
