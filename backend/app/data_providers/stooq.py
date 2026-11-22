"""stooq provider — REUSES vendor backtest.loaders.stooq_loader via adapter.

Free EOD US-equity CSV, no API key. Symbol format: AAPL.US (stooq lowercase
tickers; our adapter passes through the vendor symbol mapping). Daily only.
Rate limiting is handled by the vendor loader's shared host throttle.
"""

from __future__ import annotations

from .base import ERR_UPSTREAM_BLOCKED, Capabilities, Category
from .vendor_shim import VendorLoaderProvider


class StooqProvider(VendorLoaderProvider):
    id = "stooq"
    name_en = "Stooq (free EOD, US)"
    name_ar = "Stooq (أسعار إغلاق أمريكية مجانية)"
    markets = ("us_equity",)
    intervals = ("1D",)
    license_class = "public_free"
    adjusted = False  # raw CSV closes; no split/dividend adjustment
    vendor_module = "backtest.loaders.stooq_loader"
    min_interval_s = 0.6  # matches vendor default per-IP spacing
    # Stooq latches an anti-bot challenge for the source IP. Park the provider
    # for five minutes (shared through the DB) instead of retrying every call.
    cooldown_s = 300.0
    no_data_code = ERR_UPSTREAM_BLOCKED  # Stooq challenge = upstream blocked
    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity",),
        timeframes=("1D",),
        supports_adjusted=False,
        rate_limit_per_minute=60,
        description_en="Stooq free end-of-day US equity data",
        description_ar="بيانات إغلاق يومية مجانية للأسهم الأمريكية من Stooq",
    )

    def fetch_ohlcv_raw(self, symbol: str, start: str, end: str, interval: str = "1D") -> object:
        if "." not in symbol:
            symbol = f"{symbol}.US"  # convenience: AAPL -> AAPL.US
        return super().fetch_ohlcv_raw(symbol, start, end, interval)
