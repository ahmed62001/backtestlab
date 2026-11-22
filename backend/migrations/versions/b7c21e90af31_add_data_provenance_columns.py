"""add data provenance columns to backtests

Revision ID: b7c21e90af31
Revises: 5d8a7492f5a8
Create Date: 2026-10-19 08:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c21e90af31'
down_revision: Union[str, Sequence[str], None] = '5d8a7492f5a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = [
    ('data_provider', sa.String(32), ''),
    ('data_symbol', sa.String(32), ''),
    ('data_interval', sa.String(16), ''),
    ('data_start', sa.String(32), ''),
    ('data_end', sa.String(32), ''),
    ('data_hash', sa.String(80), ''),
]


def upgrade() -> None:
    for name, typ, _default in _COLS:
        op.add_column('backtests',
                      sa.Column(name, typ, nullable=False, server_default=''))
    op.add_column('backtests',
                  sa.Column('data_rows', sa.Integer(), nullable=False,
                            server_default='0'))


def downgrade() -> None:
    op.drop_column('backtests', 'data_rows')
    for name, _typ, _default in reversed(_COLS):
        op.drop_column('backtests', name)
