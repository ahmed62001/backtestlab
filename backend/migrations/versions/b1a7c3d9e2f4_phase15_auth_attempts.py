"""phase 15: shared auth-attempt ledger for login lockout

Revision ID: b1a7c3d9e2f4
Revises: 9c4e7a2b1f30
Create Date: 2026-11-09 00:00:00.000000

The previous login limiter lived in process memory. With more than one API
replica (or a worker/CLI sharing the same account), each process counted
independently, so the effective threshold multiplied by the number of
processes. ``auth_attempts`` makes the failure window shared and durable.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1a7c3d9e2f4"
down_revision: str | Sequence[str] | None = "9c4e7a2b1f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope_key", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_attempts_scope_key", "auth_attempts", ["scope_key"])
    op.create_index("ix_auth_attempts_created_at", "auth_attempts", ["created_at"])
    op.create_index(
        "ix_auth_attempts_scope_created", "auth_attempts", ["scope_key", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_attempts_scope_created", table_name="auth_attempts")
    op.drop_index("ix_auth_attempts_created_at", table_name="auth_attempts")
    op.drop_index("ix_auth_attempts_scope_key", table_name="auth_attempts")
    op.drop_table("auth_attempts")
