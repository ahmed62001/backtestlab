"""reliability: worker leases/heartbeats, retry metadata and hot-query indexes

Revision ID: 8f2c1d4e6a90
Revises: cf69763c1c4c
Create Date: 2026-11-03 02:30:00.000000

Phase 10 — every statement has a working downgrade (batch mode keeps the
downgrade working on SQLite < 3.35 too).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2c1d4e6a90"
down_revision: str | Sequence[str] | None = "cf69763c1c4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_COLUMNS = [
    ("attempts", sa.Integer(), "0"),
    ("max_attempts", sa.Integer(), "3"),
    ("started_at", sa.String(length=32), ""),
    ("finished_at", sa.String(length=32), ""),
    ("heartbeat_at", sa.String(length=32), ""),
    ("lease_expires_at", sa.String(length=32), ""),
    ("next_attempt_at", sa.String(length=32), ""),
    ("worker_id", sa.String(length=64), ""),
]

_INDEXES = [
    ("ix_backtests_user_created", "backtests", ["user_id", "created_at"]),
    ("ix_backtests_user_status", "backtests", ["user_id", "status"]),
    ("ix_jobs_status_next_attempt", "jobs", ["status", "next_attempt_at"]),
    ("ix_jobs_status_lease", "jobs", ["status", "lease_expires_at"]),
    ("ix_jobs_user_created", "jobs", ["user_id", "created_at"]),
    ("ix_usage_user_day", "usage", ["user_id", "day"]),
]


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        for name, typ, default in _JOB_COLUMNS:
            batch.add_column(
                sa.Column(name, typ, nullable=False, server_default=default)
            )
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, unique=False)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
    with op.batch_alter_table("jobs") as batch:
        for name, _typ, _default in reversed(_JOB_COLUMNS):
            batch.drop_column(name)
