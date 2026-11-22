"""phase 15: shared provider cooldown state

Revision ID: c3e9f1a2b4d6
Revises: b1a7c3d9e2f4
Create Date: 2026-11-09 00:00:00.000000

Stooq (and other anti-bot sources) answer a challenge page when a shared IP is
abused. Retrying from another worker process only deepens the block. This table
lets every process observe the same cooldown window.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e9f1a2b4d6"
down_revision: str | Sequence[str] | None = "b1a7c3d9e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_state",
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("cooldown_until", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("reason", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(length=32), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("provider_id"),
    )


def downgrade() -> None:
    op.drop_table("provider_state")
