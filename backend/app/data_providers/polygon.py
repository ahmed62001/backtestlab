"""Massive (formerly Polygon.io) provider — direct HTTP implementation.

US equities, crypto, forex market data via Massive API (https://api.massive.com).
Prefers MASSIVE_API_KEY environment variable; POLYGON_API_KEY accepted for
backward compatibility.
Free tier: 5 requests/minute.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx
import pandas as pd

from .base import (
    ERR_INVALID_KEY,
    ERR_NOT_CONFIGURED,
    ERR_NOT_ENTITLED,
    ERR_RATE_LIMITED,
    ERR_UNKNOWN_SYMBOL,
    ERR_UPSTREAM_UNAVAILABLE,
    Capabilities,
    Category,
    DataProvider,
    ProviderError,
    classify_error,
    get_httpx_client,
    resolve_env_key,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.massive.com"
_DEFAULT_MIN_INTERVAL = 12.0  # 5 req/min = 12s between calls
_MAX_PAGES = 10

_KEY_PLACEHOLDERS = {"", "your_massive_api_key", "your_polygon_api_key", "demo", "changeme"}

_INTERVAL_MAP = {
    "1m": ("minute", 1),
    "5m": ("minute", 5),
    "15m": ("minute", 15),
    "30m": ("minute", 30),
    "1H": ("hour", 1),
    "4H": ("hour", 4),
    "1D": ("day", 1),
    "1W": ("week", 1),
    "1M": ("month", 1),
}


_FIAT_AND_METALS = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "CNH", "EGP",
        "SEK", "NOK", "SAR", "AED", "MXN", "ZAR", "TRY", "SGD", "HKD",
        "XAU", "XAG", "XPT", "XPD",
    }
)


class PolygonProvider(DataProvider):
    id = "polygon"
    name_en = "Massive (formerly Polygon.io — US equities, crypto, forex, metals)"
    name_ar = "Massive (سابقًا Polygon.io — أسهم أمريكية، عملات مشفرة، فوركس، معادن)"
    markets = ("us_equity", "crypto", "fx", "commodity")
    intervals = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M")
    license_class = "freemium"
    adjusted = True
    requires_key = True
    min_interval_s = _DEFAULT_MIN_INTERVAL
    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity", "crypto", "fx", "commodity"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        supports_adjusted=True,
        requires_package=None,
        requires_key_env="MASSIVE_API_KEY",
        requires_key_env_legacy="POLYGON_API_KEY",
        rate_limit_per_minute=5,
        description_en="Massive (formerly Polygon.io) institutional-grade US market data",
        description_ar="بيانات سوق أمريكية ذات جودة مؤسسية من Massive (سابقًا Polygon.io)",
    )

    def _resolve_key(self) -> str:
        return resolve_env_key("MASSIVE_API_KEY", "POLYGON_API_KEY", _KEY_PLACEHOLDERS)

    def _polygon_symbol(self, symbol: str) -> str:
        upper = symbol.upper().strip()
        if upper.startswith(("X:", "C:")):
            return upper
        # Canonical FX pairs are six letters (EURUSD); Polygon's forex/metals class is
        # C: (e.g. C:EURUSD, C:XAUUSD), distinct from crypto's X: prefix.
        if len(upper) == 6 and upper.isalpha():
            return f"C:{upper}"
        if "/" in upper:
            base, quote = upper.split("/", 1)
            if base in _FIAT_AND_METALS and quote in _FIAT_AND_METALS:
                return f"C:{base}{quote}"
            if quote in ("USD", "USDT", "USDC"):
                return f"X:{base}{quote}"
            return f"C:{base}{quote}"
        if upper.endswith(("-USD", "-USDT")):
            return f"X:{upper.replace('-', '')}"
        if upper.endswith(".US"):
            return upper[:-3]
        return upper

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        api_key = self._resolve_key()
        if not api_key:
            raise ProviderError(
                self.id,
                ERR_NOT_CONFIGURED,
                f"MASSIVE_API_KEY (or POLYGON_API_KEY) not configured (required for {self.id})",
            )

        poly_symbol = self._polygon_symbol(symbol)
        interval_map = _INTERVAL_MAP.get(interval)
        if interval_map is None:
            raise ProviderError(
                self.id, "BAD_INPUT", f"unsupported interval {interval!r} for Massive"
            )
        timespan, multiplier = interval_map

        client = get_httpx_client(self.id, timeout=30.0)
        headers = {"Authorization": f"Bearer {api_key}"}

        params: dict[str, str | int | bool] = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
        }

        end_eff = end or dt.date.today().isoformat()
        start_eff = start or (dt.date.fromisoformat(end_eff[:10]) - dt.timedelta(days=365)).isoformat()
        url: str | None = (
            f"{_BASE_URL}/v2/aggs/ticker/{poly_symbol}/range/{multiplier}/{timespan}/{start_eff}/{end_eff}"
        )

        results: list[dict[str, Any]] = []
        pages = 0
        while url and pages < _MAX_PAGES:
            pages += 1
            try:
                resp = client.get(url, params=params if pages == 1 else None, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if status_code == 401:
                    raise ProviderError(self.id, ERR_INVALID_KEY, "invalid Massive API key") from e
                if status_code == 403:
                    raise ProviderError(
                        self.id,
                        ERR_NOT_ENTITLED,
                        f"Massive account not entitled for {symbol!r} ({interval})",
                    ) from e
                raise classify_error(self.id, e) from e
            except httpx.RequestError as e:
                raise classify_error(self.id, e) from e

            status_val = str(data.get("status", ""))
            if status_val == "ERROR":
                msg = str(data.get("error", "Unknown error"))
                if "rate limit" in msg.lower() or "quota" in msg.lower():
                    raise ProviderError(self.id, ERR_RATE_LIMITED, msg)
                if "not_authorized" in msg.lower() or "not entitled" in msg.lower():
                    raise ProviderError(self.id, ERR_NOT_ENTITLED, msg)
                if "not found" in msg.lower() or "invalid" in msg.lower():
                    raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, msg)
                raise ProviderError(self.id, ERR_UPSTREAM_UNAVAILABLE, msg)
            if status_val == "NOT_AUTHORIZED":
                raise ProviderError(
                    self.id,
                    ERR_NOT_ENTITLED,
                    str(data.get("message", f"Massive account not entitled for {symbol!r}")),
                )

            results.extend(data.get("results", []) or [])
            next_url = data.get("next_url")
            url = str(next_url) if isinstance(next_url, str) and next_url.startswith("https://") else None

        if not results:
            raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"no data for {symbol!r} from Massive")

        rows = []
        for row in results:
            try:
                ts = pd.Timestamp(row["t"], unit="ms", tz="UTC")
                rows.append(
                    {
                        "timestamp": ts,
                        "open": float(row["o"]),
                        "high": float(row["h"]),
                        "low": float(row["l"]),
                        "close": float(row["c"]),
                        "volume": float(row.get("v", 0)),
                    }
                )
            except (KeyError, ValueError):
                continue

        if not rows:
            raise ProviderError(
                self.id, ERR_UNKNOWN_SYMBOL, f"no valid bars for {symbol!r} from Massive"
            )

        df = pd.DataFrame(rows).set_index("timestamp")
        df = df.sort_index()
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    def health_check(self) -> dict[str, Any]:
        api_key = self._resolve_key()
        if not api_key:
            return {"available": False, "detail": "MASSIVE_API_KEY not configured"}
        try:
            client = get_httpx_client(self.id, timeout=10.0)
            resp = client.get(
                f"{_BASE_URL}/v2/aggs/ticker/AAPL/range/1/day/2023-01-01/2023-01-02",
                params={"adjusted": "true", "limit": 1},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ERROR":
                    return {"available": False, "detail": data.get("error", "API error")}
                return {"available": True, "detail": ""}
            if resp.status_code == 403:
                return {"available": True, "detail": "authenticated (entitlement-scoped)"}
            return {"available": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "detail": str(e)}
