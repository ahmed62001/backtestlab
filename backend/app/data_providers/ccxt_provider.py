"""ccxt provider — REUSES vendor backtest.loaders.ccxt_loader via adapter.

PUBLIC SPOT MARKET DATA ONLY (no API keys, no trading). Optional: requires the
`ccxt` pip package (NOT in requirements.txt). Exchange via CCXT_EXCHANGE env
(default binance). Symbol format: BTC/USDT (vendor mapping handles USDT->USD
variants). Crypto prices can be fetched here, but the backtest ENGINE still
rejects crypto assets at the adapter boundary (spot-equity product rule).
"""

from __future__ import annotations

from .base import Capabilities, Category
from .vendor_shim import VendorLoaderProvider


class CcxtProvider(VendorLoaderProvider):
    id = "ccxt"
    name_en = "Crypto exchanges (ccxt, public)"
    name_ar = "منصات العملات الرقمية (عام فقط)"
    markets = ("crypto",)
    intervals = ("1D", "1H", "4H", "1W")
    license_class = "public_free"
    adjusted = False
    vendor_module = "backtest.loaders.ccxt_loader"
    min_interval_s = 0.5
    capabilities = Capabilities(
        category=Category.CRYPTO,
        asset_classes=("crypto",),
        timeframes=("1D", "1H", "4H", "1W"),
        supports_adjusted=False,
        requires_package="ccxt",
        rate_limit_per_minute=120,
        description_en="Public crypto OHLCV via ccxt exchanges (no key)",
        description_ar="بيانات عملات رقمية عامة عبر منصات ccxt (بدون مفتاح)",
    )
