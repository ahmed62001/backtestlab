"""Config-driven TTL policy for market-data-store coverage rows.

Rules (Phase 2.2 item 7):

- intraday timeframes expire quickly (``DATA_STORE_TTL_INTRADAY_MINUTES``);
- daily/weekly/monthly ranges that end more than ``DATA_STORE_TTL_DAILY_DAYS``
  ago are historical and never expire;
- recent daily ranges (including the "current" bar) expire after
  ``DATA_STORE_TTL_RECENT_HOURS`` so they are refreshed.

All values are read from the environment at call time, which keeps tests and
long-running processes able to override them without a restart.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast

import pandas as pd

INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h"}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_range_end(range_end: str) -> datetime | None:
    if not range_end:
        return None
    try:
        ts = pd.Timestamp(range_end, tz="UTC")
    except Exception:  # noqa: BLE001
        return None
    if pd.isna(ts):
        return None
    return cast(datetime, ts.to_pydatetime())


def expires_at_for(timeframe: str, range_end: str, now: datetime | None = None) -> str | None:
    """Return an ISO expires_at for a coverage row, or None = never expires."""
    tf = timeframe or "1d"
    current = now or _now()
    end = _parse_range_end(range_end)

    if tf in INTRADAY_TIMEFRAMES:
        minutes = int(os.environ.get("DATA_STORE_TTL_INTRADAY_MINUTES", "60"))
        return (current + timedelta(minutes=minutes)).isoformat()

    daily_days = int(os.environ.get("DATA_STORE_TTL_DAILY_DAYS", "7"))
    if end is not None and end < current - timedelta(days=daily_days):
        return None
    hours = int(os.environ.get("DATA_STORE_TTL_RECENT_HOURS", "24"))
    return (current + timedelta(hours=hours)).isoformat()


def is_expired(expires_at: str | None, now: datetime | None = None) -> bool:
    """True when an ISO expires_at is in the past."""
    if not expires_at:
        return False
    current = now or _now()
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= current
