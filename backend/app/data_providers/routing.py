"""Intelligent Asset-Specific Provider Routing System.

Determines the optimal data provider for each instrument based on:
- Asset class & market type (spot vs futures)
- Account credentials & verified provider availability
- Supported timeframes and intervals
- Instrument-specific compatibility rules
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .base import DataProvider, ProviderError

logger = logging.getLogger("backtestlab.data_providers.routing")


def _is_configured(provider_id: str) -> bool:
    from ..instruments import _provider_configured

    return _provider_configured(provider_id)


def _is_cooling_down(provider_id: str) -> bool:
    from .cooldown import cooldown_status

    status = cooldown_status(provider_id)
    return bool(status.get("active"))


def get_asset_routing_candidates(symbol: str, interval: str = "1D") -> list[str]:
    """Return ordered candidate provider IDs for an instrument.

    Follows authoritative asset-class hierarchy:
      - Crypto: Twelve Data (primary when configured) -> Binance Public -> CCXT -> Polygon -> Yahoo Finance
      - Spot Precious Metals (XAU/USD): Twelve Data (primary when configured) -> Polygon
      - Commodity Futures (GC=F, SI=F, CL=F, etc.): Yahoo Finance
      - Forex: Twelve Data (primary when configured) -> Polygon -> Frankfurter (reference)
      - US Equities: Twelve Data (primary when configured) -> Polygon -> Yahoo Finance -> Stooq
      - Global / Regional Equities (Tadawul, etc.): Yahoo Finance -> Twelve Data
      - Indices: Yahoo Finance -> Twelve Data
      - Macro / Economic / Interest Rates: FRED
    """
    from ..instruments import get_instrument, normalize_symbol

    canonical = normalize_symbol(symbol)
    inst = get_instrument(canonical)
    if inst is None:
        return []

    ac = inst.asset_class
    market_type = str(inst.metadata.get("market_type", "spot"))
    exchange = str(inst.metadata.get("exchange", "")).upper()

    order: list[str] = []
    if ac == "crypto":
        order = ["twelvedata", "binance_public", "ccxt", "polygon", "yfinance"]
    elif ac == "commodity":
        if market_type == "spot" or canonical in ("XAU/USD", "XAG/USD", "XPT/USD", "XPD/USD"):
            order = ["twelvedata", "polygon"]
        else:
            order = ["yfinance"]
    elif ac == "fx":
        order = ["twelvedata", "polygon", "frankfurter"]
    elif ac in ("equity", "etf"):
        if exchange in ("TADAWUL", "KRX", "HKEX") or canonical.endswith((".SR", ".KS", ".HK")):
            order = ["yfinance", "twelvedata"]
        else:
            order = ["twelvedata", "polygon", "yfinance", "stooq", "alphavantage"]
    elif ac == "index":
        order = ["yfinance", "twelvedata"]
    elif ac == "macro_reference":
        order = ["fred"]
    else:
        order = list(inst.providers)

    # Filter to only providers listed on the instrument that support interval
    from .registry import _ALL, enabled_ids

    enabled = set(enabled_ids())
    eligible: list[str] = []
    for pid in order:
        if pid in inst.providers and pid in enabled:
            cls = _ALL.get(pid)
            if cls is not None:
                p = cls()
                if interval in p.intervals:
                    eligible.append(pid)

    return eligible


def resolve_primary_provider(symbol: str, interval: str = "1D") -> str:
    """Resolve the highest-priority configured and healthy provider for symbol."""
    candidates = get_asset_routing_candidates(symbol, interval)
    if not candidates:
        from ..instruments import get_instrument, normalize_symbol

        inst = get_instrument(normalize_symbol(symbol))
        if inst and inst.providers:
            return inst.providers[0]
        return "yfinance"

    # Pick first candidate that is configured and not in cooldown
    for pid in candidates:
        if _is_configured(pid) and not _is_cooling_down(pid):
            return pid

    # If all configured ones are in cooldown, pick the first configured
    for pid in candidates:
        if _is_configured(pid):
            return pid

    # Fallback to the first candidate (which will raise appropriate configuration error)
    return candidates[0]


def resolve_provider_for_instrument(
    symbol: str,
    requested: str | None = None,
    interval: str = "1D",
    user_id: str | None = None,
) -> DataProvider:
    """Resolve the appropriate provider instance for a symbol request.

    If requested is specified and supported, honors it.
    If requested is omitted/None:
      - If DATA_PROVIDER_DEFAULT is explicitly set in the environment (e.g. In tests with 'local' or 'synthetic')
        and supports the symbol, honors it.
      - Otherwise, routes to the intelligent primary provider for the instrument's asset class.
    """
    from .registry import _ALL, get_provider

    req = (requested or "").strip()
    if req:
        return get_provider(req, user_id=user_id)

    explicit_default = os.environ.get("DATA_PROVIDER_DEFAULT", "").strip()
    if explicit_default and explicit_default in _ALL:
        if explicit_default == "local":
            try:
                p = _ALL["local"]()
                p._resolve(symbol)
                return get_provider("local", user_id=user_id)
            except Exception:
                pass
        elif explicit_default in ("synthetic", "csv_upload"):
            return get_provider(explicit_default, user_id=user_id)

    primary_id = resolve_primary_provider(symbol, interval)
    return get_provider(primary_id, user_id=user_id)
