"""phase 14 integrity constraints: usage/idempotency/coverage uniqueness + reset tokens

Revision ID: 9c4e7a2b1f30
Revises: 8f2c1d4e6a90
Create Date: 2026-11-06 00:00:00.000000

Adds the database-level guarantees required by the pre-Phase-15 audit:

* ``usage(user_id, day)`` is unique so the daily quota can be reserved
  atomically (D-PH5-01).
* ``jobs(user_id, idem_key)`` is unique for non-empty keys so concurrent
  idempotent submits cannot create two jobs (D-PH5-02).
* ``refresh_tokens(jti)`` is unique (rotation/reuse integrity).
* ``market_coverage`` has one logical row per range (D-PH3-12).
* ``password_resets`` stores single-use reset-token hashes.

Existing duplicate rows are collapsed before the constraints are created so the
migration is safe on a populated database.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4e7a2b1f30"
down_revision: str | Sequence[str] | None = "8f2c1d4e6a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dedupe_usage() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT user_id, day, SUM(used) AS total FROM usage GROUP BY user_id, day")
    ).fetchall()
    conn.execute(sa.text("DELETE FROM usage"))
    for user_id, day, total in rows:
        conn.execute(
            sa.text("INSERT INTO usage (user_id, day, used) VALUES (:u, :d, :n)"),
            {"u": user_id, "d": day, "n": int(total or 0)},
        )


def _dedupe_coverage() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM market_coverage WHERE id NOT IN ("
            " SELECT MIN(id) FROM market_coverage"
            " GROUP BY instrument_id, provider, timeframe, adjusted, range_start, range_end)"
        )
    )


def _dedupe_jobs() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE jobs SET idem_key = '' WHERE idem_key <> '' AND id NOT IN ("
            " SELECT MIN(id) FROM jobs WHERE idem_key <> '' GROUP BY user_id, idem_key)"
        )
    )


def _dedupe_refresh_tokens() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM refresh_tokens WHERE id NOT IN ("
            " SELECT MIN(id) FROM refresh_tokens GROUP BY jti)"
        )
    )


def upgrade() -> None:
    _dedupe_usage()
    _dedupe_coverage()
    _dedupe_jobs()
    _dedupe_refresh_tokens()

    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.String(length=32), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])
    op.create_index("ix_password_resets_token_hash", "password_resets", ["token_hash"], unique=True)

    with op.batch_alter_table("usage") as batch:
        batch.create_unique_constraint("uq_usage_user_day", ["user_id", "day"])
    # The model declares ``jti`` as ``unique=True, index=True``, which is a
    # single unique index (not a separate unique constraint). Match that shape
    # exactly so ``alembic check`` reports no drift.
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)
    with op.batch_alter_table("market_coverage") as batch:
        batch.create_unique_constraint(
            "uq_market_coverage_key",
            ["instrument_id", "provider", "timeframe", "adjusted", "range_start", "range_end"],
        )

    op.create_index(
        "uq_jobs_user_idem",
        "jobs",
        ["user_id", "idem_key"],
        unique=True,
        sqlite_where=sa.text("idem_key <> ''"),
        postgresql_where=sa.text("idem_key <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_user_idem", table_name="jobs")
    with op.batch_alter_table("market_coverage") as batch:
        batch.drop_constraint("uq_market_coverage_key", type_="unique")
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=False)
    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint("uq_usage_user_day", type_="unique")
    op.drop_index("ix_password_resets_token_hash", table_name="password_resets")
    op.drop_index("ix_password_resets_user_id", table_name="password_resets")
    op.drop_table("password_resets")
