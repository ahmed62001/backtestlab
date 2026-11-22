"""Tiingo provider — REUSES vendor backtest.loaders.tiingo_loader via adapter.

US-equity daily OHLCV via Tiingo REST API (requires TIINGO_API_KEY).
Supports adjusted closes (total-return prices).
"""

from __future__ import annotations

from .base import Capabilities, Category
from .vendor_shim import VendorLoaderProvider


class TiingoProvider(VendorLoaderProvider):
    id = "tiingo"
    name_en = "Tiingo (US equities, adjusted)"
    name_ar = "Tiingo (أسهم أمريكية معدلة)"
    markets = ("us_equity",)
    intervals = ("1D",)
    license_class = "freemium"
    adjusted = True  # Tiingo provides adjusted OHLC
    vendor_module = "backtest.loaders.tiingo_loader"
    min_interval_s = 0.5
    requires_key = True
    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity",),
        timeframes=("1D",),
        supports_adjusted=True,
        requires_package=None,
        requires_key_env="TIINGO_API_KEY",
        rate_limit_per_minute=60,
        description_en="Tiingo US equity EOD data with split/dividend-adjusted prices",
        description_ar="بيانات نهاية اليوم الأمريكية من Tiingo مع أسعار معدلة للتقسيمات والأرباح",
    )
