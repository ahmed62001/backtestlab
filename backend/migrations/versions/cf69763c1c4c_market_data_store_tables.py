"""market_data_store_tables

Revision ID: cf69763c1c4c
Revises: b7c21e90af31
Create Date: 2026-10-30 17:19:52.341621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf69763c1c4c'
down_revision: Union[str, Sequence[str], None] = 'b7c21e90af31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create market data store tables."""
    op.create_table(
        'market_instruments',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('asset_class', sa.String(length=16), nullable=False),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('exchange', sa.String(length=32), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'asset_class', name='uq_market_instrument_symbol_asset_class'),
    )
    op.create_index(op.f('ix_market_instruments_asset_class'), 'market_instruments', ['asset_class'], unique=False)
    op.create_index(op.f('ix_market_instruments_exchange'), 'market_instruments', ['exchange'], unique=False)
    op.create_index(op.f('ix_market_instruments_symbol'), 'market_instruments', ['symbol'], unique=False)

    op.create_table(
        'market_bars',
        sa.Column('instrument_id', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('timeframe', sa.String(length=8), nullable=False),
        sa.Column('ts', sa.String(length=32), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Float(), nullable=True),
        sa.Column('adjusted', sa.Boolean(), nullable=False),
        sa.Column('ingested_at', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['market_instruments.id'], ),
        sa.PrimaryKeyConstraint('instrument_id', 'provider', 'timeframe', 'ts', 'adjusted'),
    )
    op.create_index('ix_market_bars_instrument_timeframe_ts', 'market_bars', ['instrument_id', 'timeframe', 'ts'], unique=False)
    op.create_index(op.f('ix_market_bars_ts'), 'market_bars', ['ts'], unique=False)

    op.create_table(
        'market_coverage',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('instrument_id', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('timeframe', sa.String(length=8), nullable=False),
        sa.Column('adjusted', sa.Boolean(), nullable=False),
        sa.Column('range_start', sa.String(length=32), nullable=False),
        sa.Column('range_end', sa.String(length=32), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('data_hash', sa.String(length=64), nullable=True),
        sa.Column('fetched_at', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.String(length=32), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('last_error_code', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['market_instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_market_coverage_adjusted'), 'market_coverage', ['adjusted'], unique=False)
    op.create_index('ix_market_coverage_expires_at', 'market_coverage', ['expires_at'], unique=False)
    op.create_index('ix_market_coverage_instrument_id', 'market_coverage', ['instrument_id'], unique=False)
    op.create_index('ix_market_coverage_provider', 'market_coverage', ['provider'], unique=False)
    op.create_index('ix_market_coverage_range_end', 'market_coverage', ['range_end'], unique=False)
    op.create_index('ix_market_coverage_range_start', 'market_coverage', ['range_start'], unique=False)
    op.create_index('ix_market_coverage_status', 'market_coverage', ['status'], unique=False)
    op.create_index('ix_market_coverage_timeframe', 'market_coverage', ['timeframe'], unique=False)


def downgrade() -> None:
    """Drop market data store tables."""
    op.drop_index('ix_market_coverage_timeframe', table_name='market_coverage')
    op.drop_index('ix_market_coverage_status', table_name='market_coverage')
    op.drop_index('ix_market_coverage_range_start', table_name='market_coverage')
    op.drop_index('ix_market_coverage_range_end', table_name='market_coverage')
    op.drop_index('ix_market_coverage_provider', table_name='market_coverage')
    op.drop_index('ix_market_coverage_instrument_id', table_name='market_coverage')
    op.drop_index(op.f('ix_market_coverage_adjusted'), table_name='market_coverage')
    op.drop_index('ix_market_coverage_expires_at', table_name='market_coverage')
    op.drop_table('market_coverage')
    op.drop_index('ix_market_bars_ts', table_name='market_bars')
    op.drop_index('ix_market_bars_instrument_timeframe_ts', table_name='market_bars')
    op.drop_table('market_bars')
    op.drop_index('ix_market_instruments_symbol', table_name='market_instruments')
    op.drop_index('ix_market_instruments_exchange', table_name='market_instruments')
    op.drop_index('ix_market_instruments_asset_class', table_name='market_instruments')
    op.drop_table('market_instruments')
