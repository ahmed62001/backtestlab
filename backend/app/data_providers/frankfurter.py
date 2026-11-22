"""Frankfurter provider — direct HTTP implementation.

Free FX rates from European Central Bank via frankfurter.dev API.
No API key required. Daily rates only.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

from .base import (
    ERR_UNKNOWN_SYMBOL,
    Capabilities,
    Category,
    DataProvider,
    ProviderError,
    classify_error,
    get_httpx_client,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.frankfurter.dev/v1"
_DEFAULT_MIN_INTERVAL = 0.5

# Currency mapping
_FX_PAIRS = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "USDCHF": ("USD", "CHF"),
    "AUDUSD": ("AUD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "EURGBP": ("EUR", "GBP"),
    "EURJPY": ("EUR", "JPY"),
}


class FrankfurterProvider(DataProvider):
    id = "frankfurter"
    name_en = "Frankfurter (ECB FX rates)"
    name_ar = "Frankfurter (أسعار صرف ECB)"
    markets = ("fx",)
    intervals = ("1D",)
    license_class = "public_free"
    adjusted = False
    requires_key = False
    min_interval_s = _DEFAULT_MIN_INTERVAL
    capabilities = Capabilities(
        category=Category.FX,
        asset_classes=("fx_reference",),
        timeframes=("1D",),
        supports_adjusted=False,
        requires_package=None,
        requires_key_env=None,
        rate_limit_per_minute=60,
        description_en="ECB daily FX reference rates via frankfurter.dev (reference only, not tradable OHLCV)",
        description_ar="أسعار صرف مرجعية يومية من البنك المركزي الأوروبي (مرجعية فقط، ليست بيانات OHLCV قابلة للتداول)",
    )

    def _parse_pair(self, symbol: str) -> tuple[str, str] | None:
        upper = symbol.upper().strip()
        if upper in _FX_PAIRS:
            return _FX_PAIRS[upper]
        if len(upper) == 6 and upper[3:] in ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"):
            return upper[:3], upper[3:]
        return None

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        pair = self._parse_pair(symbol)
        if pair is None:
            raise ProviderError(
                self.id, ERR_UNKNOWN_SYMBOL, f"unsupported FX pair for Frankfurter: {symbol!r}"
            )

        base, quote = pair
        client = get_httpx_client(self.id, timeout=30.0)

        # Frankfurter API: /v1/{start}..{end}?from=BASE&to=QUOTE
        url = f"{_BASE_URL}/{start}..{end}"
        params = {"from": base, "to": quote}

        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise classify_error(self.id, e) from e
        except httpx.RequestError as e:
            raise classify_error(self.id, e) from e

        rates = data.get("rates", {})
        if not rates:
            raise ProviderError(
                self.id, ERR_UNKNOWN_SYMBOL, f"no FX data for {symbol!r} from Frankfurter"
            )

        # Build DataFrame with rate as close price
        # frankfurter.dev returns rates as {date: {quote: rate}} (nested)
        # or {date: rate} (legacy flat). Handle both formats.
        rows = []
        for date_str, rate_val in sorted(rates.items()):
            if isinstance(rate_val, dict):
                rate_val = rate_val.get(quote)
                if rate_val is None:
                    continue
            rows.append(
                {
                    "timestamp": pd.Timestamp(date_str, tz="UTC"),
                    "open": rate_val,
                    "high": rate_val,
                    "low": rate_val,
                    "close": rate_val,
                    "volume": 0.0,  # FX spot has no volume
                }
            )
        df = pd.DataFrame(rows).set_index("timestamp")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    def health_check(self) -> dict[str, Any]:
        try:
            client = get_httpx_client(self.id, timeout=10.0)
            resp = client.get(f"{_BASE_URL}/latest", params={"from": "EUR", "to": "USD"})
            if resp.status_code == 200:
                return {"available": True, "detail": ""}
            return {"available": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "detail": str(e)}
