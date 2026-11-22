"""synthetic provider: deterministic seeded GBM OHLCV bars (dev/tests only).

Same philosophy as the old demo engine data: seeded by sha256(symbol|range) so
identical requests return identical bars. Never used as a silent fallback —
only when explicitly selected (default in ENV=test).
"""

from __future__ import annotations

import hashlib
import random

import pandas as pd

from .base import Capabilities, Category, DataProvider, ProviderError


def _rng(seed: str) -> random.Random:
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return random.Random(h)


def generate_gbm_bars(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Seeded GBM daily bars (252 trading days/year) with OHLC + volume."""
    start_ts = pd.Timestamp(start or "2022-01-01", tz="UTC")
    end_ts = pd.Timestamp(end or "2023-12-31", tz="UTC")
    if start_ts >= end_ts:
        raise ProviderError("synthetic", "BAD_INPUT", "start must precede end")
    r = _rng(f"{symbol}|{start}|{end}")
    dates = pd.bdate_range(start_ts, end_ts)
    if len(dates) == 0:
        raise ProviderError("synthetic", "EMPTY_DATA", "no business days in range")
    px = 100.0
    rows = []
    for _ in dates:
        ret = 0.0004 + (r.random() - 0.5) * 0.02
        o = px
        c = px * (1 + ret)
        hi = max(o, c) * (1 + r.random() * 0.004)
        lo = min(o, c) * (1 - r.random() * 0.004)
        vol = float(1_000_000 + int(r.random() * 500_000))
        rows.append((o, hi, lo, c, vol))
        px = c
    df = pd.DataFrame(rows, index=dates, columns=["open", "high", "low", "close", "volume"])
    df.index.name = "trade_date"
    return df


class SyntheticProvider(DataProvider):
    id = "synthetic"
    name_en = "Synthetic (seeded GBM, dev)"
    name_ar = "اصطناعي (تطوير فقط)"
    markets = ("equity",)
    intervals = ("1D",)
    license_class = "dev_only"
    adjusted = False
    capabilities = Capabilities(
        category=Category.SYNTHETIC,
        asset_classes=("equity",),
        timeframes=("1D",),
        supports_adjusted=False,
        rate_limit_per_minute=0,
        description_en="Deterministic seeded synthetic bars (development only)",
        description_ar="بيانات اصطناعية حتمية (للتطوير فقط)",
    )

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        return generate_gbm_bars(symbol, start, end)
