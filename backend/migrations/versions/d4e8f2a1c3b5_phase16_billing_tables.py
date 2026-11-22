"""phase16 billing tables

Revision ID: d4e8f2a1c3b5
Revises: c3e9f1a2b4d6
Create Date: 2026-11-20 20:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e8f2a1c3b5"
down_revision = "c3e9f1a2b4d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_customers",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=128), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_period_end", sa.String(length=32), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_billing_customers_customer_id", "billing_customers", ["customer_id"])
    op.create_index("ix_billing_customers_subscription_id", "billing_customers", ["subscription_id"])

    op.create_table(
        "billing_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_index("ix_billing_customers_subscription_id", table_name="billing_customers")
    op.drop_index("ix_billing_customers_customer_id", table_name="billing_customers")
    op.drop_table("billing_customers")
