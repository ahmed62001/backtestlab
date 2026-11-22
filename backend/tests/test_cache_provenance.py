"""Phase 3 — cache provenance must report the real fetch time.

A cache hit used to stamp ``fetched_at = now``, so a 20-hour-old series
claimed ``cache_age = 0`` and looked freshly fetched. That made every
"cached" badge untruthful.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import time

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_test.db")

from app.data_providers.base import DataProvider, _cache_file, cache_key  # noqa: E402


def _frame():
    import pandas as pd

    idx = pd.date_range("2026-11-01", periods=5, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 101, 102, 103, 104],
            "high": [102.0, 103, 104, 105, 106],
            "low": [99.0, 100, 101, 102, 103],
            "close": [101.0, 102, 103, 104, 105],
            "volume": [1000.0, 1100, 1200, 1300, 1400],
        },
        index=idx,
    )


class _Provider(DataProvider):
    id = "yfinance"
    intervals = ("1D", "1H")
    license_class = "test"

    def fetch_ohlcv_raw(self, symbol, start, end, interval="1D"):
        return _frame()


def test_cache_hit_reports_real_fetch_age():
    p = _Provider()
    symbol = "CACHEPROBE"
    start, end = "2026-10-01", "2026-12-01"
    key = cache_key(p.id, symbol, start, end, "1D")
    path = _cache_file(key)
    if path.exists():
        path.unlink()

    first = p.fetch_ohlcv_cached(symbol, start, end, "1D")
    assert first.provenance["cache"] == "miss"
    assert first.provenance["served_from_cache"] is False
    assert first.provenance["cache_age_s"] == 0

    # Simulate a 3-hour-old cache entry.
    age = 3 * 3600
    old = time.time() - age
    os.utime(path, (old, old))

    second = p.fetch_ohlcv_cached(symbol, start, end, "1D")
    assert second.provenance["cache"] == "hit"
    assert second.provenance["served_from_cache"] is True
    assert abs(second.provenance["cache_age_s"] - age) <= 5
    fetched = dt.datetime.fromisoformat(second.provenance["fetched_at"])
    assert abs((dt.datetime.now(dt.UTC) - fetched).total_seconds() - age) <= 5


def test_cache_miss_fetched_at_is_now():
    p = _Provider()
    symbol = "CACHEPROBE2"
    start, end = "2026-10-02", "2026-12-02"
    path = _cache_file(cache_key(p.id, symbol, start, end, "1D"))
    if path.exists():
        path.unlink()
    result = p.fetch_ohlcv_cached(symbol, start, end, "1D")
    fetched = dt.datetime.fromisoformat(result.provenance["fetched_at"])
    assert abs((dt.datetime.now(dt.UTC) - fetched).total_seconds()) < 5
    pytest.approx(result.provenance["cache_age_s"], abs=1) == 0
