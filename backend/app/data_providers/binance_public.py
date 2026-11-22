"""Binance Public provider — REUSES vendor backtest.loaders.binance_loader via adapter.

Public spot/perpetual OHLCV via Binance REST (no API key required).
Supports crypto markets with multiple intervals.
"""

from __future__ import annotations

from .base import Capabilities, Category
from .vendor_shim import VendorLoaderProvider


class BinancePublicProvider(VendorLoaderProvider):
    id = "binance_public"
    name_en = "Binance Public (crypto)"
    name_ar = "بينانس العام (عملات مشفرة)"
    markets = ("crypto",)
    intervals = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M")
    license_class = "public_free"
    adjusted = False  # raw exchange prices
    vendor_module = "backtest.loaders.binance_loader"
    min_interval_s = 0.1
    requires_key = False
    capabilities = Capabilities(
        category=Category.CRYPTO,
        asset_classes=("crypto",),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        supports_adjusted=False,
        requires_package="ccxt",
        requires_key_env=None,
        rate_limit_per_minute=1200,
        description_en="Binance public REST API for crypto spot and perpetual futures",
        description_ar="واجهة برمجة تطبيقات بينانس العامة للعملات المشفرة الفورية والعقود الدائمة",
    )
