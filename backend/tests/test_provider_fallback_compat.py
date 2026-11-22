"""Phase 3: provider fallback must never change the economic meaning of data.

All providers are deterministic doubles; no network is used.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest


def _bars(start: str = "2022-01-01", end: str = "2022-12-31", base: float = 100.0):
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    rows = []
    for i, _ts in enumerate(idx):
        close = base * (1.0 + 0.0003 * i + 0.03 * math.sin(i / 11.0))
        open_ = close * (1.0 + 0.001 * math.sin(i / 3.0))
        rows.append(
            (open_, max(open_, close) * 1.003, min(open_, close) * 0.997, close, 1000.0 + i)
        )
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


@pytest.fixture(autouse=True)
def _fast_providers(monkeypatch, tmp_path):
    import app.data_providers.base as base_mod
    import app.data_providers.registry as reg

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(base_mod.RATE_LIMITER, "wait", lambda *a, **k: None)
    monkeypatch.setattr(reg, "FALLBACK_ENABLED", True)


def _fail(provider: str, code: str = "UPSTREAM_UNAVAILABLE"):
    def inner(self, symbol, start, end, interval="1D"):
        from app.data_providers.base import ProviderError

        raise ProviderError(provider, code, "simulated upstream failure")

    return inner


def test_compatible_fallback_preserves_instrument_and_semantics(monkeypatch):
    from app.data_providers.alphavantage import AlphaVantageProvider
    from app.data_providers.registry import fetch_bars
    from app.data_providers.stooq import StooqProvider

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", _fail("stooq"))
    monkeypatch.setattr(AlphaVantageProvider, "fetch_ohlcv_raw", lambda *a, **k: _bars())

    provider, result = fetch_bars("stooq", "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert provider.id == "alphavantage"
    pv = result.provenance
    assert pv["provider"] == "alphavantage"
    assert pv["requested_provider"] == "stooq"
    assert pv["fallback"] is True
    assert pv["fallback_from"] == "stooq"
    assert "stooq" in pv["fallback_reason"]
    assert "UPSTREAM_UNAVAILABLE" in pv["fallback_reason"]
    assert pv["symbol"] == "AAPL"
    assert pv["asset_class"] == "equity"
    assert pv["quote_currency"] == "USD"
    assert pv["price_adjustment"] == "unadjusted"


def test_compatible_crypto_fallback_keeps_quote_currency(monkeypatch):
    from app.data_providers.binance_public import BinancePublicProvider
    from app.data_providers.ccxt_provider import CcxtProvider
    from app.data_providers.registry import fetch_bars

    monkeypatch.setattr(BinancePublicProvider, "fetch_ohlcv_raw", _fail("binance_public"))
    monkeypatch.setattr(CcxtProvider, "fetch_ohlcv_raw", lambda *a, **k: _bars(base=30000.0))

    provider, result = fetch_bars("binance_public", "BTC-USDT", "2022-01-01", "2022-12-31", "1D")
    assert provider.id == "ccxt"
    pv = result.provenance
    assert pv["fallback"] is True
    assert pv["fallback_from"] == "binance_public"
    assert pv["symbol"] == "BTC-USDT"
    assert pv["quote_currency"] == "USDT"
    assert pv["asset_class"] == "crypto"


def test_adjusted_vs_unadjusted_never_falls_back(monkeypatch):
    """yfinance is adjusted; stooq is unadjusted: both are real equity
    providers for AAPL, but substitution would change price semantics."""
    from app.data_providers.registry import fetch_bars
    from app.data_providers.stooq import StooqProvider
    from app.data_providers.yfinance_provider import YFinanceProvider

    monkeypatch.setattr(YFinanceProvider, "fetch_ohlcv_raw", _fail("yfinance"))

    def must_not_run(self, symbol, start, end, interval="1D"):
        raise AssertionError("unadjusted stooq must not substitute for adjusted yfinance")

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", must_not_run)

    with pytest.raises(Exception) as ei:
        fetch_bars("yfinance", "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert getattr(ei.value, "provider", None) == "yfinance"
    assert getattr(ei.value, "code", None) == "UPSTREAM_UNAVAILABLE"


def test_non_market_provider_never_falls_back_to_real_data(monkeypatch):
    from app.data_providers.local_fixtures import LocalFixturesProvider
    from app.data_providers.registry import fetch_bars
    from app.data_providers.yfinance_provider import YFinanceProvider

    monkeypatch.setattr(LocalFixturesProvider, "fetch_ohlcv_raw", _fail("local"))

    def must_not_run(self, symbol, start, end, interval="1D"):
        raise AssertionError("live yfinance must not substitute for a local fixture")

    monkeypatch.setattr(YFinanceProvider, "fetch_ohlcv_raw", must_not_run)

    with pytest.raises(Exception) as ei:
        fetch_bars("local", "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert getattr(ei.value, "provider", None) == "local"


def test_validation_errors_do_not_fall_back(monkeypatch):
    from app.data_providers.alphavantage import AlphaVantageProvider
    from app.data_providers.registry import fetch_bars
    from app.data_providers.stooq import StooqProvider

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", _fail("stooq", "UNKNOWN_SYMBOL"))

    def must_not_run(self, symbol, start, end, interval="1D"):
        raise AssertionError("fallback must not hide an unsupported symbol")

    monkeypatch.setattr(AlphaVantageProvider, "fetch_ohlcv_raw", must_not_run)

    with pytest.raises(Exception) as ei:
        fetch_bars("stooq", "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert getattr(ei.value, "provider", None) == "stooq"
    assert getattr(ei.value, "code", None) == "UNKNOWN_SYMBOL"


def test_fallback_rejects_inadequate_historical_coverage(monkeypatch):
    from app.data_providers.alphavantage import AlphaVantageProvider
    from app.data_providers.registry import fetch_bars
    from app.data_providers.stooq import StooqProvider

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", _fail("stooq"))
    # A materially shorter window must not silently become the backtest's data.
    monkeypatch.setattr(
        AlphaVantageProvider,
        "fetch_ohlcv_raw",
        lambda *a, **k: _bars(start="2022-12-01", end="2022-12-31"),
    )

    with pytest.raises(Exception) as ei:
        fetch_bars("stooq", "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert getattr(ei.value, "provider", None) == "stooq"
    assert "fallback attempted" in str(ei.value)


def test_primary_error_reason_is_preserved_when_all_fallbacks_fail(monkeypatch):
    from app.data_providers.alphavantage import AlphaVantageProvider
    from app.data_providers.registry import fetch_bars
    from app.data_providers.stooq import StooqProvider

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", _fail("stooq"))
    monkeypatch.setattr(AlphaVantageProvider, "fetch_ohlcv_raw", _fail("alphavantage"))

    with pytest.raises(Exception) as ei:
        fetch_bars("stooq", "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert getattr(ei.value, "provider", None) == "stooq"
    assert "simulated upstream failure" in str(ei.value)
    assert "alphavantage" in str(ei.value)
