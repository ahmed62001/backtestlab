"""yfinance provider — REUSES vendor backtest.loaders.yfinance_loader via adapter.

Optional: requires the `yfinance` pip package (NOT in requirements.txt; install
it manually or the provider reports available=false). Handles US/A/global
tickers + crypto via Yahoo. Closes are Yahoo auto-adjusted by the vendor loader.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import threading
import time
from typing import Any

from .base import Capabilities, Category, ERR_UNKNOWN_SYMBOL, ProviderError, classify_error
from .vendor_shim import VendorLoaderProvider

_YF_INTRADAY_MAX_DAYS: dict[str, int] = {
    "1m": 7,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "1H": 720,
    "4H": 720,
}

_yf_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_yf_quote_lock = threading.Lock()
_YF_QUOTE_TTL_S = float(os.environ.get("YFINANCE_QUOTE_CACHE_TTL_S", "30.0"))


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


class YFinanceProvider(VendorLoaderProvider):
    id = "yfinance"
    name_en = "Yahoo Finance (yfinance)"
    name_ar = "ياهو فاينانس"
    markets = ("us_equity", "global_equity", "crypto", "commodity", "index")
    intervals = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M")
    license_class = "public_free"
    adjusted = True  # yfinance auto-adjusted closes (vendor loader default)
    vendor_module = "backtest.loaders.yfinance_loader"
    min_interval_s = 0.25
    localize_intraday = True
    market_types = ("spot", "futures")
    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity", "etf", "index", "crypto", "fx", "commodity"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        supports_adjusted=True,
        requires_package="yfinance",
        rate_limit_per_minute=60,
        description_en="Yahoo Finance daily/intraday bars (free, no key)",
        description_ar="أسعار ياهو فاينانس اليومية واللحظية (مجانية بدون مفتاح)",
    )

    def _map_symbol(self, symbol: str) -> str:
        s = symbol.strip().upper()
        if s in ("^TASI", "TASI"):
            return "^TASI.SR"
        if len(s) == 6 and s.isalpha() and not s.startswith("^"):
            # Canonical 6-letter FX pairs on Yahoo Finance use the =X suffix (EURUSD=X)
            from ..instruments import get_instrument

            inst = get_instrument(s)
            if inst is not None and inst.asset_class == "fx":
                return f"{s}=X"
        return symbol

    def _clamp_intraday_start(self, start: str, end: str, interval: str) -> str:
        max_days = _YF_INTRADAY_MAX_DAYS.get(interval)
        if not max_days or not start:
            return start
        try:
            now_date = dt.datetime.now(dt.UTC).date()
            start_d = dt.date.fromisoformat(start[:10])
            end_d = dt.date.fromisoformat(end[:10]) if end else now_date
        except ValueError:
            return start
        # Only clamp recent lookbacks (leaves historical fixture tests untouched)
        if (now_date - end_d).days <= max_days:
            earliest = now_date - dt.timedelta(days=max_days)
            if start_d < earliest:
                return earliest.isoformat()
        return start

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ):
        yf_sym = self._map_symbol(symbol)
        eff_start = self._clamp_intraday_start(start, end, interval)
        return super().fetch_ohlcv_raw(yf_sym, eff_start, end, interval=interval)

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch near-real-time / latest quote for ``symbol`` via yfinance fast_info.

        Uses a short in-memory TTL (30s) so commodities, indices, metal futures,
        and global equities refresh without hitting the 24h daily bar cache.
        """
        now_mono = time.monotonic()
        with _yf_quote_lock:
            cached = _yf_quote_cache.get(symbol)
            if cached is not None and (now_mono - cached[0]) < _YF_QUOTE_TTL_S:
                return cached[1]

        try:
            import yfinance as yf  # noqa: PLC0415
        except Exception as e:
            raise ProviderError(self.id, "PROVIDER_NOT_CONFIGURED", f"yfinance not installed: {e}") from e

        yf_sym = self._map_symbol(symbol)
        try:
            ticker = yf.Ticker(yf_sym)
            fi = ticker.fast_info
            price = _safe_float(getattr(fi, "last_price", None))
            prev_close = _safe_float(getattr(fi, "previous_close", None)) or _safe_float(
                getattr(fi, "regular_market_previous_close", None)
            )
            day_high = _safe_float(getattr(fi, "day_high", None))
            day_low = _safe_float(getattr(fi, "day_low", None))
            volume = _safe_float(getattr(fi, "last_volume", None)) or 0.0
        except Exception as e:
            raise classify_error(self.id, e) from e

        if price is None or price <= 0:
            raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"no fast_info quote for {symbol!r}")

        change: float | None = None
        change_pct: float | None = None
        if prev_close is not None and prev_close > 0:
            change = price - prev_close
            change_pct = (change / prev_close) * 100.0

        now_utc = dt.datetime.now(dt.UTC)
        is_open = False
        try:
            from ..instruments import get_instrument
            from ..market_sessions import session_for

            inst = get_instrument(symbol)
            if inst is not None:
                is_open = session_for(inst.asset_class, inst.symbol).is_open(now_utc)
        except Exception:
            is_open = False

        entry = {
            "symbol": symbol,
            "price": price,
            "prevClose": prev_close,
            "change": change,
            "changePct": change_pct,
            "dayHigh": day_high if day_high is not None else price,
            "dayLow": day_low if day_low is not None else price,
            "volume": max(0.0, volume),
            "isMarketOpen": is_open,
            "datetime": now_utc.isoformat(),
        }
        with _yf_quote_lock:
            _yf_quote_cache[symbol] = (now_mono, entry)
        return entry
