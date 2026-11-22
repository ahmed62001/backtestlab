"""Market data store package.

Provides a persistent, provider-agnostic local market-data database (SQLite dev /
PostgreSQL prod) that caches/stores everything fetched, so backtests are fast,
repeatable, and work offline once data is ingested.
"""

from __future__ import annotations

from .service import MarketDataService

__all__ = ["MarketDataService"]
