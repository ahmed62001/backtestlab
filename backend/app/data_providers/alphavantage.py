"""alphavantage provider — REUSES vendor backtest.loaders.alphavantage_loader.

KEYED STUB: requires env ALPHAVANTAGE_API_KEY; disabled (available=false)
when the key is absent or a placeholder value. Free tier is rate-limited per
key/IP — the vendor loader throttles (default 1s spacing), we add our own
min_interval too. Daily US-equity bars, unadjusted.
"""

from __future__ import annotations

import os

from .base import Capabilities, Category
from .vendor_shim import VendorLoaderProvider

_API_KEY_ENV = "ALPHAVANTAGE_API_KEY"
_PLACEHOLDERS = {"", "your-alphavantage-api-key", "demo"}


def configured_key() -> str:
    key = os.environ.get(_API_KEY_ENV, "").strip()
    return "" if key in _PLACEHOLDERS else key


class AlphaVantageProvider(VendorLoaderProvider):
    id = "alphavantage"
    name_en = "Alpha Vantage (keyed)"
    name_ar = "ألفا فانتاج (يتطلب مفتاح)"
    markets = ("us_equity",)
    intervals = ("1D",)
    requires_key = True
    license_class = "keyed_free_tier"
    adjusted = False  # TIME_SERIES_DAILY is unadjusted
    vendor_module = "backtest.loaders.alphavantage_loader"
    min_interval_s = 1.0
    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity",),
        timeframes=("1D",),
        supports_adjusted=False,
        requires_key_env=_API_KEY_ENV,
        rate_limit_per_minute=5,
        description_en="Alpha Vantage keyed US equity daily bars (unadjusted)",
        description_ar="بيانات أسهم أمريكية يومية من Alpha Vantage غير معدلة تتطلب مفتاحًا",
    )

    def health_check(self) -> dict:
        if not configured_key():
            return {"available": False, "detail": f"{_API_KEY_ENV} not configured"}
        return super().health_check()
