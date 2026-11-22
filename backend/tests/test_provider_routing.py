"""Tests for intelligent asset-specific provider routing, fallback compatibility,
and instrument identity preservation.
"""

from __future__ import annotations

import pytest
import pandas as pd

from app.instruments import get_instrument, normalize_symbol, asset_class_for
from app.data_providers.routing import (
    get_asset_routing_candidates,
    resolve_primary_provider,
    resolve_provider_for_instrument,
)
from app.data_providers.registry import _providers_compatible, fetch_bars
from app.data_providers.base import ProviderError, BarsResult


def test_asset_class_mapping_all_categories():
    assert asset_class_for("BTC-USD") == "crypto"
    assert asset_class_for("ETH-USDT") == "crypto"
    assert asset_class_for("XAU/USD") == "commodity"
    assert asset_class_for("GC=F") == "commodity"
    assert asset_class_for("SI=F") == "commodity"
    assert asset_class_for("CL=F") == "commodity"
    assert asset_class_for("NG=F") == "commodity"
    assert asset_class_for("ZC=F") == "commodity"
    assert asset_class_for("EURUSD") == "fx"
    assert asset_class_for("GBPUSD") == "fx"
    assert asset_class_for("AAPL") == "equity"
    assert asset_class_for("2222.SR") == "equity"
    assert asset_class_for("^GSPC") == "index"
    assert asset_class_for("^TASI") == "index"
    assert asset_class_for("FRED:GDP") == "macro_reference"
    assert asset_class_for("FRED:CPI") == "macro_reference"


def test_asset_routing_candidates_preferences():
    # Crypto: twelvedata -> binance_public -> ccxt
    crypto_cands = get_asset_routing_candidates("BTC-USD", "1D")
    assert "twelvedata" in crypto_cands
    assert "binance_public" in crypto_cands
    assert "ccxt" in crypto_cands

    # Spot metals: twelvedata
    metals_spot_cands = get_asset_routing_candidates("XAU/USD", "1D")
    assert "twelvedata" in metals_spot_cands

    # Commodity futures: yfinance
    futures_cands = get_asset_routing_candidates("GC=F", "1D")
    assert "yfinance" in futures_cands

    # Energy: yfinance
    energy_cands = get_asset_routing_candidates("CL=F", "1D")
    assert "yfinance" in energy_cands

    # Agriculture: yfinance
    agri_cands = get_asset_routing_candidates("ZC=F", "1D")
    assert "yfinance" in agri_cands

    # Equities: twelvedata, yfinance, stooq
    eq_cands = get_asset_routing_candidates("AAPL", "1D")
    assert "yfinance" in eq_cands
    assert "stooq" in eq_cands


def test_incompatible_cross_asset_fallback_prevented():
    """Ensure spot instruments never fall back to futures contracts or vice-versa."""
    # Spot gold (XAU/USD) must NEVER substitute with gold futures (GC=F)
    assert _providers_compatible("twelvedata", "yfinance", "XAU/USD", "1D") is False

    # Gold futures (GC=F) must NEVER substitute with spot gold provider
    assert _providers_compatible("yfinance", "twelvedata", "GC=F", "1D") is False

    # Equity must NEVER fall back to a crypto exchange
    assert _providers_compatible("yfinance", "binance_public", "AAPL", "1D") is False
    assert _providers_compatible("yfinance", "ccxt", "AAPL", "1D") is False

    # Crypto must NEVER fall back to an equity provider (stooq)
    assert _providers_compatible("twelvedata", "stooq", "BTC-USD", "1D") is False
    assert _providers_compatible("binance_public", "stooq", "BTC-USD", "1D") is False

    # FX feeds have incompatible volume/pricing models; no fallback allowed
    assert _providers_compatible("twelvedata", "polygon", "EURUSD", "1D") is False
    assert _providers_compatible("twelvedata", "yfinance", "EURUSD", "1D") is False


def test_symbol_aliases_normalization():
    assert normalize_symbol("^TASI.SR") == "^TASI"
    assert normalize_symbol("TASI.SR") == "^TASI"
    assert normalize_symbol("GC") == "GC=F"
    assert normalize_symbol("SI") == "SI=F"
    assert normalize_symbol("CL") == "CL=F"
    assert normalize_symbol("NG") == "NG=F"
    assert normalize_symbol("BZ") == "BZ=F"
    assert normalize_symbol("BTC/USD") == "BTC-USD"
    assert normalize_symbol("BTC/USDT") == "BTC-USDT"
    assert normalize_symbol("EUR/USD") == "EURUSD"


def test_automatic_failover_mechanism(monkeypatch, tmp_path):
    """Verify that when primary provider encounters transient failure,
    it automatically fails over to the next compatible provider in asset preferences."""
    import app.data_providers.base as base_mod
    import app.data_providers.registry as reg
    from app.data_providers.twelvedata import TwelveDataProvider
    from app.data_providers.binance_public import BinancePublicProvider

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.delenv("DATA_PROVIDER_DEFAULT", raising=False)
    monkeypatch.setenv("TWELVEDATA_API_KEY", "real-key-123")

    # Simulate Twelve Data failure for BTC-USD
    def fail_twelvedata(self, symbol, start, end, interval="1D"):
        raise ProviderError(self.id, "UPSTREAM_UNAVAILABLE", "simulated TwelveData outage")

    monkeypatch.setattr(TwelveDataProvider, "fetch_ohlcv_raw", fail_twelvedata)

    # Mock successful fallback on Binance Public with adequate coverage (>= 10 bars)
    dates = pd.date_range("2024-01-01", periods=15, freq="D", tz="UTC")
    sample_df = pd.DataFrame(
        {
            "open": [42000.0 + i * 100 for i in range(15)],
            "high": [43500.0 + i * 100 for i in range(15)],
            "low": [41500.0 + i * 100 for i in range(15)],
            "close": [43000.0 + i * 100 for i in range(15)],
            "volume": [100.0 + i * 10 for i in range(15)],
        },
        index=dates,
    )

    def mock_binance(self, symbol, start, end, interval="1D"):
        return sample_df

    monkeypatch.setattr(BinancePublicProvider, "fetch_ohlcv_raw", mock_binance)

    # Call fetch_bars with requested=None (router picks primary twelvedata, falls back to binance_public)
    provider, result = reg.fetch_bars(
        None, "BTC-USD", "2024-01-01", "2024-01-15", "1D", allow_fallback=True
    )

    assert provider.id == "binance_public"
    assert result.provenance["provider"] == "binance_public"
    assert result.provenance["fallback"] is True
    assert result.provenance["fallback_from"] == "twelvedata"
    assert "simulated TwelveData outage" in result.provenance["fallback_reason"]
    assert len(result.frame) == 15
