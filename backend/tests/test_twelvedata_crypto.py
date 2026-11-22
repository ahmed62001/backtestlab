"""Tests for Twelve Data Cryptocurrency integration, reference endpoints,
symbol normalization, envelope validation, and error classification.
"""

from __future__ import annotations

import pytest
import respx
import httpx
import pandas as pd

from app.data_providers.twelvedata import TwelveDataProvider
from app.data_providers.base import ProviderError


def test_twelvedata_crypto_capabilities():
    p = TwelveDataProvider()
    assert "crypto" in p.capabilities.asset_classes
    assert "crypto" in p.markets
    assert "commodity" in p.capabilities.asset_classes
    assert "1D" in p.intervals
    assert "1H" in p.intervals
    assert "5m" in p.intervals


def test_twelvedata_symbol_and_exchange_normalization():
    p = TwelveDataProvider()
    
    # Crypto pairs default to configured exchange if present (e.g. Binance)
    sym, exc = p._twelvedata_symbol_and_exchange("BTC-USD")
    assert sym == "BTC/USD"
    assert exc == "Binance"  # resolved from instrument metadata
    
    sym, exc = p._twelvedata_symbol_and_exchange("BTC-USDT")
    assert sym == "BTC/USDT"
    assert exc == "Binance"
    
    # Explicit exchange prefix/suffix with " spot" stripping
    sym, exc = p._twelvedata_symbol_and_exchange("BTC-USDT:Binance spot")
    assert sym == "BTC/USDT"
    assert exc == "Binance"  # " spot" stripped

    sym, exc = p._twelvedata_symbol_and_exchange("BINANCE:ETH-USD")
    assert sym == "ETH/USD"
    assert exc == "BINANCE"
    
    # Spot metals
    sym, exc = p._twelvedata_symbol_and_exchange("XAU/USD")
    assert sym == "XAU/USD"
    
    # Forex
    sym, exc = p._twelvedata_symbol_and_exchange("EURUSD")
    assert sym == "EUR/USD"


@respx.mock
def test_twelvedata_cryptocurrencies_reference(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    p = TwelveDataProvider()
    
    mock_response = {
        "data": [
            {
                "symbol": "BTC/USD",
                "available_exchanges": ["Binance", "Coinbase Pro", "Kraken"],
                "currency_base": "Bitcoin",
                "currency_quote": "US Dollar",
            },
            {
                "symbol": "ETH/BTC",
                "available_exchanges": ["Binance", "Huobi"],
                "currency_base": "Ethereum",
                "currency_quote": "Bitcoin",
            },
        ],
        "status": "ok",
    }
    
    respx.get("https://api.twelvedata.com/cryptocurrencies").respond(
        status_code=200,
        json=mock_response,
    )
    
    pairs = p.get_cryptocurrencies()
    assert len(pairs) == 2
    assert pairs[0]["symbol"] == "BTC/USD"
    
    # Pair validation
    assert p.validate_cryptocurrency_pair("BTC/USD") is True
    assert p.validate_cryptocurrency_pair("BTC/USD", exchange="Binance") is True
    assert p.validate_cryptocurrency_pair("BTC/USD", exchange="NonExistent") is False
    assert p.validate_cryptocurrency_pair("FAKE/PAIR") is False


@respx.mock
def test_twelvedata_cryptocurrency_exchanges_reference(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    p = TwelveDataProvider()
    
    mock_response = {
        "data": ["Binance", "Bitfinex", "Coinbase Pro", "Kraken"],
        "status": "ok",
    }
    
    respx.get("https://api.twelvedata.com/cryptocurrency_exchanges").respond(
        status_code=200,
        json=mock_response,
    )
    
    exchanges = p.get_cryptocurrency_exchanges()
    assert "Binance" in exchanges
    assert "Kraken" in exchanges
    assert len(exchanges) == 4


@respx.mock
def test_twelvedata_crypto_historical_ohlcv_normalization(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    p = TwelveDataProvider()
    
    mock_candles = {
        "meta": {
            "symbol": "BTC/USD",
            "interval": "1day",
            "currency_base": "Bitcoin",
            "currency_quote": "US Dollar",
            "type": "Cryptocurrency",
        },
        "values": [
            {
                "datetime": "2024-01-02",
                "open": "44000.0",
                "high": "45500.0",
                "low": "43800.0",
                "close": "45000.0",
                "volume": "12500",
            },
            {
                "datetime": "2024-01-01",
                "open": "42500.0",
                "high": "44200.0",
                "low": "42200.0",
                "close": "44000.0",
                "volume": "10200",
            },
        ],
        "status": "ok",
    }
    
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,
        json=mock_candles,
    )
    
    df = p.fetch_ohlcv_raw("BTC-USD", "2024-01-01", "2024-01-02", "1D")
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing
    assert df.loc["2024-01-01 00:00:00+00:00", "close"] == 44000.0
    assert df.loc["2024-01-02 00:00:00+00:00", "high"] == 45500.0


@respx.mock
def test_twelvedata_envelope_validation_normalization(monkeypatch):
    """Enforces rule 5: High >= max(Open, Close) and Low <= min(Open, Close) via envelope validation."""
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    p = TwelveDataProvider()
    
    # Inverted High / Low candle
    bad_candles = {
        "values": [
            {
                "datetime": "2024-01-01",
                "open": "44000.0",
                "high": "40000.0",  # High < Open -> normalized to >= Open
                "low": "45000.0",   # Low > Close -> normalized to <= Close
                "close": "43500.0",
                "volume": "1000",
            }
        ],
        "status": "ok",
    }
    
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,
        json=bad_candles,
    )
    
    df = p.fetch_ohlcv_raw("BTC-USD", "2024-01-01", "2024-01-02", "1D")
    row = df.iloc[0]
    assert row["high"] >= max(row["open"], row["close"])
    assert row["low"] <= min(row["open"], row["close"])


@respx.mock
def test_twelvedata_rate_limit_error_classification(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    p = TwelveDataProvider()
    
    rate_limit_response = {
        "code": 429,
        "message": "You have reached your API call rate limit: 8 requests per minute.",
        "status": "error",
    }
    
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,  # Twelve Data often returns 200 with code=429 in JSON body
        json=rate_limit_response,
    )
    
    with pytest.raises(ProviderError) as exc_info:
        p.fetch_ohlcv_raw("BTC-USD", "2024-01-01", "2024-01-02", "1D")
    assert exc_info.value.code == "RATE_LIMITED"
    assert exc_info.value.retry_after == 60.0


@respx.mock
def test_twelvedata_invalid_api_key_classification(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "invalid-key")
    p = TwelveDataProvider()
    
    auth_error_response = {
        "code": 401,
        "message": "Invalid API key.",
        "status": "error",
    }
    
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=401,
        json=auth_error_response,
    )
    
    with pytest.raises(ProviderError) as exc_info:
        p.fetch_ohlcv_raw("BTC-USD", "2024-01-01", "2024-01-02", "1D")
    assert exc_info.value.code == "PROVIDER_INVALID_KEY"
