"""initial schema

Revision ID: 3d13a8f5db3f
Revises: 
Create Date: 2026-10-18 23:20:29.289962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d13a8f5db3f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('email', sa.String(320), unique=True, index=True, nullable=False),
        sa.Column('name', sa.String(200), server_default='', nullable=False),
        sa.Column('password_hash', sa.String(300), server_default='', nullable=False),
        sa.Column('plan', sa.String(16), server_default='free', nullable=False),
        sa.Column('language', sa.String(8), server_default='ar', nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
    )
    op.create_table(
        'backtests',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id'), index=True, nullable=False),
        sa.Column('name', sa.String(300), server_default='', nullable=False),
        sa.Column('template_id', sa.String(64), server_default='ma-crossover', nullable=False),
        sa.Column('asset', sa.String(32), server_default='AAPL', nullable=False),
        sa.Column('status', sa.String(16), server_default='done', nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('total_return_pct', sa.Float, server_default='0', nullable=False),
        sa.Column('max_drawdown_pct', sa.Float, server_default='0', nullable=False),
        sa.Column('sharpe', sa.Float, server_default='0', nullable=False),
        sa.Column('win_rate_pct', sa.Float, server_default='0', nullable=False),
        sa.Column('trades', sa.Integer, server_default='0', nullable=False),
        sa.Column('vs_buy_hold_pct', sa.Float, server_default='0', nullable=False),
        sa.Column('config_json', sa.Text, server_default='{}', nullable=False),
        sa.Column('result_json', sa.Text, server_default='{}', nullable=False),
    )
    op.create_table(
        'usage',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.String(64), index=True, nullable=False),
        sa.Column('day', sa.String(16), index=True, nullable=False),
        sa.Column('used', sa.Integer, server_default='0', nullable=False),
    )
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(64), index=True, nullable=False),
        sa.Column('backtest_id', sa.String(64), server_default='', nullable=False),
        sa.Column('status', sa.String(16), server_default='queued', nullable=False),
        sa.Column('progress', sa.Integer, server_default='0', nullable=False),
        sa.Column('idem_key', sa.String(128), index=True, server_default='', nullable=False),
        sa.Column('config_json', sa.Text, server_default='{}', nullable=False),
        sa.Column('error', sa.Text, server_default='', nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('jobs')
    op.drop_table('usage')
    op.drop_table('backtests')
    op.drop_table('users')
