"""local_store provider: serve bars from the persistent market data store only.

This provider never touches the network. It is marked available only when the
store contains at least one ``complete`` coverage row, and it reports a compact
summary of stored instruments/timeframes/ranges through the catalog.
Requesting an uncovered symbol/range raises ``DATA_NOT_IN_STORE`` — there is no
network fall-through.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Capabilities, Category, DataProvider, ProviderError

_STORE_TIMEFRAMES = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
}


def _store_timeframe(interval: str) -> str:
    if interval == "1M":
        return "1M"
    return str(interval).lower()


class LocalStoreProvider(DataProvider):
    id = "local_store"
    name_en = "Local data store"
    name_ar = "مخزن البيانات المحلي"
    markets = ("stored",)
    intervals = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M")
    license_class = "local_store"
    adjusted: bool | None = None

    capabilities = Capabilities(
        category=Category.LOCAL,
        asset_classes=("equity", "etf", "index", "crypto", "fx", "macro", "other"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        supports_adjusted=True,
        rate_limit_per_minute=0,
        description_en="Read-only view over the local market-data store (offline)",
        description_ar="عرض للقراءة فقط على مخزن البيانات المحلي (دون اتصال)",
    )

    # ---- store inspection -------------------------------------------------
    def _summary(self) -> dict[str, Any]:
        from ..data_store.repository import coverage_summary

        return coverage_summary()

    def health_check(self) -> dict[str, Any]:
        try:
            summary = self._summary()
        except Exception as e:  # noqa: BLE001
            return {"available": False, "detail": f"store unavailable: {e}"}
        available = summary.get("completeCoverageRows", 0) > 0
        detail = (
            f"{summary.get('instrumentCount', 0)} instruments, "
            f"{len(summary.get('timeframes', []))} timeframes"
            if available
            else "store is empty"
        )
        return {"available": available, "detail": detail}

    def store_summary(self) -> dict[str, Any]:
        """Catalog metadata: what exists in the store right now."""
        try:
            return self._summary()
        except Exception as e:  # noqa: BLE001
            return {
                "instruments": [],
                "timeframes": [],
                "providers": [],
                "instrumentCount": 0,
                "completeCoverageRows": 0,
                "error": str(e),
            }

    # ---- data access -------------------------------------------------------
    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        from ..data_store.repository import read_bars_for_symbol

        timeframe = _STORE_TIMEFRAMES.get(interval, _store_timeframe(interval))
        bars = read_bars_for_symbol(symbol, timeframe, start, end)
        if not bars:
            raise ProviderError(
                self.id,
                "DATA_NOT_IN_STORE",
                f"no stored bars for {symbol!r} {timeframe} in {start}..{end}",
            )
        df = pd.DataFrame(bars)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        return df[["open", "high", "low", "close", "volume"]]
