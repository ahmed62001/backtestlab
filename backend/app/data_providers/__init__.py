"""Optional market-data providers (Phase 2). See docs/DATA_PROVIDERS.md."""

# Import all provider classes to ensure they're registered
from . import (  # noqa: F401
    alphavantage,
    binance_public,
    ccxt_provider,
    coingecko,
    csv_upload,
    frankfurter,
    fred,
    local_fixtures,
    local_store,
    polygon,
    stooq,
    synthetic,
    tiingo,
    twelvedata,
    yfinance_provider,
)
from .base import BarsResult, DataProvider, ProviderError, normalize_ohlcv  # noqa: F401
from .registry import (  # noqa: F401
    default_provider_id,
    enabled_ids,
    fetch_bars,
    get_provider,
    provider_infos,
    resolve_for_request,
)
