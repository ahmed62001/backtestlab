"""local provider: recorded fixture CSVs (backend/tests/fixtures/*.csv).

license_class=dev_only (redistribution of vendor/exchange data unclear) —
metadata only; results carry the DATA_DEV_SOURCE warning. No network.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import Capabilities, Category, DataProvider, ProviderError

FIX_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


class LocalFixturesProvider(DataProvider):
    id = "local"
    name_en = "Local fixtures (dev)"
    name_ar = "ملفات محلية (تطوير)"
    markets = ("equity",)
    intervals = ("1D",)
    license_class = "dev_only"
    adjusted = None  # unknown
    capabilities = Capabilities(
        category=Category.LOCAL,
        asset_classes=("equity",),
        timeframes=("1D",),
        supports_adjusted=False,
        rate_limit_per_minute=0,
        description_en="Local fixture CSVs for development (no network)",
        description_ar="ملفات CSV محلية للتطوير (دون اتصال)",
    )

    def __init__(self, directory: Path | str | None = None):
        self.directory = Path(directory) if directory else FIX_DIR

    def _resolve(self, symbol: str) -> Path:
        base = symbol.split(".")[0].split("-")[0]
        for cand in (self.directory / f"{symbol}.csv", self.directory / f"{base}.csv"):
            if cand.exists():
                return cand
        raise ProviderError(self.id, "UNKNOWN_SYMBOL", f"no local fixture for {symbol!r}")

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        path = self._resolve(symbol)
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        if len(df) == 0:
            raise ProviderError(
                self.id, "EMPTY_DATA", f"fixture {path.name} has no rows in {start}..{end}"
            )
        return df
