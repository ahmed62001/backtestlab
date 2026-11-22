"""Unit and integration tests for Twelve Data market charts, quotes, and streaming."""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import pytest
import respx
from httpx import Response

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_providers.base import (
    ERR_INVALID_KEY,
    ERR_NOT_CONFIGURED,
    ERR_RATE_LIMITED,
    ProviderError,
)
from app.data_providers.twelvedata import TwelveDataProvider, _quote_cache, _quote_lock
from app.main import create_app
from app.streaming import Tick, get_manager
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_cache():
    with _quote_lock:
        _quote_cache.clear()
    yield
    with _quote_lock:
        _quote_cache.clear()


@pytest.fixture(scope="module")
def client():
    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "TD Market", "email": "td_market_qa@t.com", "password": "password123"},
    )
    if r.status_code == 201:
        tok = r.json()["token"]
    else:
        r2 = c.post(
            "/api/v1/auth/login",
            json={"email": "td_market_qa@t.com", "password": "password123"},
        )
        assert r2.status_code == 200, r2.text
        tok = r2.json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# 1. Symbol Mapping and Interval Mapping
# ---------------------------------------------------------------------------

def test_twelvedata_symbol_mapping():
    provider = TwelveDataProvider()
    assert provider._twelvedata_symbol("AAPL") == "AAPL"
    assert provider._twelvedata_symbol("BTC-USD") == "BTC/USD"
    assert provider._twelvedata_symbol("BTC/USD") == "BTC/USD"
    assert provider._twelvedata_symbol("EURUSD") == "EUR/USD"
    assert provider._twelvedata_symbol("MSFT.US") == "MSFT"


def test_twelvedata_missing_key_raises(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    provider = TwelveDataProvider()
    with pytest.raises(ProviderError) as exc:
        provider.fetch_ohlcv_raw("AAPL", "2026-11-01", "2026-11-20", "1D")
    assert exc.value.code == ERR_NOT_CONFIGURED

    with pytest.raises(ProviderError) as exc2:
        provider.fetch_quote("AAPL")
    assert exc2.value.code == ERR_NOT_CONFIGURED


def test_twelvedata_invalid_interval(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    provider = TwelveDataProvider()
    with pytest.raises(ProviderError) as exc:
        provider.fetch_ohlcv_raw("AAPL", "2026-11-01", "2026-11-20", "2D")
    assert exc.value.code == "BAD_INPUT"


# ---------------------------------------------------------------------------
# 2. OHLCV Raw: Deduplication, Ordering, Envelope Validation
# ---------------------------------------------------------------------------

@respx.mock
def test_twelvedata_fetch_ohlcv_raw_success(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    provider = TwelveDataProvider()

    # Out of order timestamps, with a duplicate timestamp and flawed envelope
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=Response(
            200,
            json={
                "values": [
                    {
                        "datetime": "2026-11-02 00:00:00",
                        "open": "105.0",
                        "high": "104.0",  # High lower than open -> should be corrected by envelope validation
                        "low": "106.0",   # Low higher than open -> should be corrected by envelope validation
                        "close": "105.5",
                        "volume": "1000",
                    },
                    {
                        "datetime": "2026-11-01 00:00:00",
                        "open": "100.0",
                        "high": "102.0",
                        "low": "99.0",
                        "close": "101.0",
                        "volume": "800",
                    },
                    {
                        "datetime": "2026-11-02 00:00:00",  # Duplicate timestamp (newer in list)
                        "open": "105.0",
                        "high": "108.0",
                        "low": "104.0",
                        "close": "107.0",
                        "volume": "1500",
                    },
                ]
            },
        )
    )

    df = provider.fetch_ohlcv_raw("AAPL", "2026-11-01", "2026-11-02", "1D")
    # Must be sorted chronologically
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-11-01", "2026-11-02"]
    # Duplicate removed keeping last
    assert df.loc["2026-11-02"]["close"] == 107.0
    # Envelope validation ensures high >= max(o, c) and low <= min(o, c)
    assert df.loc["2026-11-01"]["high"] >= max(df.loc["2026-11-01"]["open"], df.loc["2026-11-01"]["close"])
    assert df.loc["2026-11-01"]["low"] <= min(df.loc["2026-11-01"]["open"], df.loc["2026-11-01"]["close"])


@respx.mock
def test_twelvedata_fetch_ohlcv_raw_rate_limit(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    provider = TwelveDataProvider()

    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=Response(
            200,
            json={
                "status": "error",
                "code": 429,
                "message": "You have run out of API credits for the current minute.",
            },
        )
    )

    with pytest.raises(ProviderError) as exc:
        provider.fetch_ohlcv_raw("AAPL", "2026-11-01", "2026-11-02", "1D")
    assert exc.value.code == ERR_RATE_LIMITED


# ---------------------------------------------------------------------------
# 3. Quotes & Caching & Batching
# ---------------------------------------------------------------------------

@respx.mock
def test_twelvedata_fetch_quote_caching(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    provider = TwelveDataProvider()

    route = respx.get("https://api.twelvedata.com/quote").mock(
        return_value=Response(
            200,
            json={
                "symbol": "AAPL",
                "close": "225.50",
                "previous_close": "220.00",
                "change": "5.50",
                "percent_change": "2.50",
                "high": "226.00",
                "low": "219.50",
                "volume": "45000000",
                "is_market_open": True,
                "datetime": "2026-11-20 16:00:00",
            },
        )
    )

    q1 = provider.fetch_quote("AAPL")
    assert q1["symbol"] == "AAPL"
    assert q1["price"] == 225.50
    assert q1["prevClose"] == 220.00
    assert q1["change"] == 5.50
    assert q1["changePct"] == 2.50
    assert q1["isMarketOpen"] is True
    assert route.call_count == 1

    # Second call within TTL must hit memory cache, not HTTP
    q2 = provider.fetch_quote("AAPL")
    assert q2["price"] == 225.50
    assert route.call_count == 1


@respx.mock
def test_twelvedata_fetch_quotes_batch_chunking(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    provider = TwelveDataProvider()

    # When querying 10 symbols, it must chunk into batches of at most 8 symbols
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ", "AMD"]

    def _batch_side_effect(request):
        syms = request.url.params["symbol"].split(",")
        assert len(syms) <= 8, f"Batch size {len(syms)} exceeds max limit 8"
        data = {}
        for s in syms:
            data[s] = {
                "symbol": s,
                "close": "100.0",
                "previous_close": "99.0",
                "change": "1.0",
                "percent_change": "1.01",
                "is_market_open": True,
                "datetime": "2026-11-20 16:00:00",
            }
        return Response(200, json=data)

    route = respx.get("https://api.twelvedata.com/quote").mock(side_effect=_batch_side_effect)

    results = provider.fetch_quotes_batch(symbols)
    assert len(results) == 10
    assert route.call_count == 2  # 8 + 2 symbols = 2 HTTP calls


# ---------------------------------------------------------------------------
# 4. Market API WebSocket Tick Overlay and Disallowed yfinance Fallback
# ---------------------------------------------------------------------------

def test_quotes_api_overlays_live_tick(client, monkeypatch):
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")

    from app.data_providers.twelvedata import TwelveDataProvider

    monkeypatch.setattr(
        TwelveDataProvider,
        "fetch_quote",
        lambda self, symbol: {
            "symbol": symbol,
            "price": 100.0,
            "prevClose": 95.0,
            "change": 5.0,
            "changePct": 5.26,
            "dayHigh": 102.0,
            "dayLow": 94.0,
            "volume": 10000.0,
            "isMarketOpen": True,
            "datetime": "2026-11-20T15:00:00+00:00",
        },
    )

    manager = get_manager()
    now = dt.datetime.now(dt.UTC)
    manager._latest_ticks["AAPL"] = Tick(
        symbol="AAPL",
        price=108.0,
        currency="USD",
        exchange="NASDAQ",
        provider_ts=now,
        received_at=now,
    )

    try:
        r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
        assert r.status_code == 200, r.text
        item = r.json()["items"][0]
        assert item["status"] == "ok"
        assert item["price"] == 108.0
        assert item["transport"] == "WEBSOCKET"
        assert item["classification"] == "REAL_TIME"
        assert item["quality"] == "live"
        # Change must be recalculated against prevClose (108 - 95 = 13)
        assert item["change"] == 13.0
        assert item["changePct"] == pytest.approx((13.0 / 95.0) * 100.0)
        assert item["dayHigh"] == 108.0  # High raised because tick > dayHigh
    finally:
        manager._latest_ticks.pop("AAPL", None)


def test_quotes_api_strictly_disallows_delayed_yfinance(client, monkeypatch):
    c, h = client
    # When Twelve Data key is missing, no silent fallback to delayed yfinance!
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["status"] == "unavailable"
    assert item["errorCode"] == "PROVIDER_NOT_CONFIGURED"
    assert item["source"] is None
