"""Celerates campaigns: per-tick cooldown jitter.

See docs/celerates-integration-v1.md. A per-recipient broadcast (batch_size=1)
must not resume at a fixed offset every time -- that pattern is as
fingerprint-able as sending everyone at once. cooldown_jitter_seconds adds a
random 0..N second extension on top of cooldown_seconds each tick.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260930_0032"
down_revision: str | None = "20260929_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE celerates_campaigns
            ADD COLUMN cooldown_jitter_seconds integer NOT NULL DEFAULT 0
                CHECK (cooldown_jitter_seconds >= 0 AND cooldown_jitter_seconds <= 86400)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE celerates_campaigns DROP COLUMN cooldown_jitter_seconds")
