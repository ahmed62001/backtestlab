"""Market read layer: universe, quotes and series (no network)."""

from __future__ import annotations

import os
import pathlib
import sys
import time

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_test.db")

import app.market as market  # noqa: E402
from app.data_providers.base import BarsResult, ProviderError  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Market", "email": "market_qa@t.com", "password": "password123"},
    )
    if r.status_code == 201:
        tok = r.json()["token"]
    else:
        r2 = c.post(
            "/api/v1/auth/login",
            json={"email": "market_qa@t.com", "password": "password123"},
        )
        assert r2.status_code == 200, r2.text
        tok = r2.json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


def _frame():
    import pandas as pd

    idx = pd.date_range("2026-11-01", periods=3, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 105.0, 110.0],
            "high": [102.0, 108.0, 115.0],
            "low": [99.0, 104.0, 109.0],
            "close": [101.0, 106.0, 112.0],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        index=idx,
    )


def _result(provider_id="twelvedata"):
    return BarsResult(frame=_frame(), provenance={"provider": provider_id})


class _FakeProv:
    id = "twelvedata"
    intervals = ("1D", "1H", "1W", "1M")


def test_universe_requires_auth():
    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/v1/market/universe")
    assert r.status_code == 401, r.text


def test_universe_contains_symbols_and_groups(client):
    c, h = client
    r = c.get("/api/v1/market/universe", headers=h)
    assert r.status_code == 200, r.text
    items = {it["symbol"]: it for it in r.json()["items"]}
    assert "GC=F" in items
    assert items["GC=F"]["group"] == "metals"
    assert items["GC=F"]["exchange"] == "CME"
    assert items["GC=F"]["assetClass"] == "commodity"
    assert "AAPL" in items
    assert items["AAPL"]["group"] == "stocks"
    assert "CL=F" in items
    assert items["CL=F"]["group"] == "commodities"
    assert "^GSPC" in items
    assert items["^GSPC"]["group"] == "indices"
    assert "BTC-USD" in items
    assert items["BTC-USD"]["group"] == "crypto"


def test_quotes_happy_path(client, monkeypatch):
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")
    from app.data_providers.twelvedata import TwelveDataProvider

    monkeypatch.setattr(
        TwelveDataProvider,
        "fetch_quote",
        lambda self, symbol: {
            "symbol": symbol,
            "price": 112.0,
            "prevClose": 106.0,
            "change": 6.0,
            "changePct": 600.0 / 106.0,
            "dayHigh": 115.0,
            "dayLow": 109.0,
            "volume": 1200.0,
            "isMarketOpen": False,
            "datetime": "2026-11-20T16:00:00+00:00",
        },
    )
    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "generatedAt" in body
    item = body["items"][0]
    assert item["status"] == "ok"
    assert item["price"] == 112.0
    assert item["prevClose"] == 106.0
    assert item["change"] == 6.0
    assert item["changePct"] == pytest.approx(600.0 / 106.0)
    assert item["dayHigh"] == 115.0
    assert item["dayLow"] == 109.0
    assert item["volume"] == 1200.0
    assert item["source"] == "twelvedata"
    assert item["quality"] == "eod"
    assert item["asOf"]


def test_quotes_fetches_symbols_concurrently(client, monkeypatch):
    """Regression R-003: a cold multi-symbol sweep must not run sequentially.

    The provider is mocked with a fixed per-call delay; fetching 8 symbols
    sequentially would take >= 8 * delay. The bounded pool must stay well
    under half of that, keeping the response inside the gateway timeout.
    """
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")
    delay = 0.25

    from app.data_providers.twelvedata import TwelveDataProvider

    def _slow(self, symbol):
        time.sleep(delay)
        return {
            "symbol": symbol,
            "price": 112.0,
            "prevClose": 106.0,
            "change": 6.0,
            "changePct": 600.0 / 106.0,
            "dayHigh": 115.0,
            "dayLow": 109.0,
            "volume": 1200.0,
            "isMarketOpen": True,
            "datetime": "2026-11-20T16:00:00+00:00",
        }

    monkeypatch.setattr(TwelveDataProvider, "fetch_quote", _slow)
    symbols = "AAPL,MSFT,NVDA,TSLA,AMD,SPY,GOOGL,AMZN"
    started = time.monotonic()
    r = c.get(f"/api/v1/market/quotes?symbols={symbols}", headers=h)
    elapsed = time.monotonic() - started

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 8
    assert all(item["status"] == "ok" for item in items)
    # 8 sequential calls would need 2.0 s; allow generous CI headroom while
    # still failing if the loop regresses to sequential execution.
    assert elapsed < delay * len(items) * 0.6, elapsed


def test_quotes_unknown_symbol(client):
    c, h = client
    r = c.get("/api/v1/market/quotes?symbols=NOPE123", headers=h)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["status"] == "unavailable"
    assert item["errorCode"] == "UNKNOWN_SYMBOL"
    assert item["quality"] == "unavailable"
    assert item["price"] is None


def test_quotes_provider_failure(client, monkeypatch):
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")
    from app.data_providers.twelvedata import TwelveDataProvider

    def _boom(*a, **k):
        raise ProviderError("twelvedata", "UPSTREAM_UNAVAILABLE", "down")

    monkeypatch.setattr(TwelveDataProvider, "fetch_quote", _boom)
    monkeypatch.setattr(market, "fetch_bars", _boom)
    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["status"] == "unavailable"
    assert item["errorCode"] == "UPSTREAM_UNAVAILABLE"

    monkeypatch.setattr(market, "fetch_bars", _boom)
    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["status"] == "unavailable"
    assert item["errorCode"] == "UPSTREAM_UNAVAILABLE"


def test_quotes_classification_and_provider_preference(client, monkeypatch):
    c, h = client

    # When Twelve Data key is not configured, delayed yfinance fallback is strictly disabled
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    item = r.json()["items"][0]
    assert item["status"] == "unavailable"
    assert item["errorCode"] == "PROVIDER_NOT_CONFIGURED"

    # When Twelve Data key is configured, twelvedata is authoritative
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key-value-123456")

    def _mock_quote(self, symbol):
        return {
            "symbol": symbol,
            "price": 200.0,
            "prevClose": 195.0,
            "change": 5.0,
            "changePct": 2.56,
            "dayHigh": 202.0,
            "dayLow": 194.0,
            "volume": 500000.0,
            "isMarketOpen": True,
            "datetime": "2026-11-20T15:30:00+00:00",
        }

    from app.data_providers.twelvedata import TwelveDataProvider
    monkeypatch.setattr(TwelveDataProvider, "fetch_quote", _mock_quote)

    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    item = r.json()["items"][0]
    assert item["status"] == "ok"
    assert item["classification"] == "REAL_TIME"
    assert item["source"] == "twelvedata"
    assert item["price"] == 200.0
    assert item["transport"] == "REST_POLLING"

    # When WebSocket live tick arrives, overlay live tick
    from app.streaming import Tick, get_manager
    import datetime as dt

    manager = get_manager()
    tick = Tick(
        symbol="AAPL",
        price=205.5,
        currency="USD",
        exchange="NASDAQ",
        provider_ts=dt.datetime.now(dt.UTC),
        received_at=dt.datetime.now(dt.UTC),
    )
    manager._latest_ticks["AAPL"] = tick

    r = c.get("/api/v1/market/quotes?symbols=AAPL", headers=h)
    item = r.json()["items"][0]
    assert item["status"] == "ok"
    assert item["price"] == 205.5
    assert item["transport"] == "WEBSOCKET"
    assert item["classification"] == "REAL_TIME"
    assert item["change"] == 205.5 - 195.0
    manager._latest_ticks.pop("AAPL", None)


def test_quotes_empty_symbols_422(client):
    c, h = client
    r = c.get("/api/v1/market/quotes?symbols=", headers=h)
    assert r.status_code == 422, r.text


def test_series_returns_bars(client, monkeypatch):
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")
    monkeypatch.setattr(market, "fetch_bars", lambda *a, **k: (_FakeProv(), _result()))
    r = c.get("/api/v1/market/series?symbol=AAPL&interval=1D&days=30", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "AAPL"
    assert body["interval"] == "1D"
    assert body["provider"] == "twelvedata"
    assert len(body["bars"]) == 3
    assert set(body["bars"][0].keys()) == {"t", "o", "h", "l", "c", "v"}
    assert body["bars"][-1]["c"] == 112.0
    assert "provenance" in body


def test_series_returns_freshness_contract(client, monkeypatch):
    """Phase 3: the series response carries machine-readable freshness fields."""
    import datetime as dt

    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")
    now = dt.datetime.now(dt.UTC)
    fetched = (now - dt.timedelta(hours=3)).isoformat()

    def _cached(requested, symbol, start, end, interval="1D", user_id=None, **kw):
        from app.data_providers.base import BarsResult

        return (
            _FakeProv(),
            BarsResult(
                frame=_frame(),
                provenance={
                    "provider": "twelvedata",
                    "cache": "hit",
                    "fetched_at": fetched,
                    "cache_age_s": 10_800,
                },
            ),
        )

    monkeypatch.setattr(market, "fetch_bars", _cached)
    r = c.get("/api/v1/market/series?symbol=AAPL&interval=1D&days=30", headers=h)
    assert r.status_code == 200, r.text
    f = r.json()["freshness"]
    assert f["provider"] == "twelvedata"
    assert f["interval"] == "1D"
    assert f["served_from_cache"] is True
    assert f["cache_age_seconds"] == 10_800
    assert f["fetched_at"] == fetched
    assert f["session"] == "us_equity"
    assert f["data_status"] in ("delayed", "stale", "fresh")
    assert f["is_stale"] == (f["data_status"] == "stale")
    assert f["last_candle_timestamp"]
    assert "last_completed_candle_timestamp" in f


def test_series_unknown_symbol_422(client):
    c, h = client
    r = c.get("/api/v1/market/series?symbol=NOPE123", headers=h)
    assert r.status_code == 422, r.text


def test_series_bad_interval_422(client, monkeypatch):
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")

    def _bad(*a, **k):
        raise ProviderError("twelvedata", "BAD_INPUT", "interval unsupported")

    monkeypatch.setattr(market, "fetch_bars", _bad)
    r = c.get("/api/v1/market/series?symbol=AAPL&interval=9X", headers=h)
    assert r.status_code == 422, r.text


def test_series_days_bounded(client):
    c, h = client
    r = c.get("/api/v1/market/series?symbol=AAPL&days=9999", headers=h)
    assert r.status_code == 422, r.text


def test_universe_metals_commodities_and_all_intraday_timeframes(client):
    """Verify metals vs commodities grouping and 1m/5m/15m/1H/4H on every instrument."""
    c, h = client
    r = c.get("/api/v1/market/universe", headers=h)
    assert r.status_code == 200, r.text
    items = {it["symbol"]: it for it in r.json()["items"]}

    for metal in ("XAU/USD", "XAG/USD", "GC=F", "SI=F", "PL=F", "PA=F", "HG=F"):
        assert metal in items
        assert items[metal]["group"] == "metals", (metal, items[metal]["group"])

    for comm in ("CL=F", "BZ=F", "NG=F", "ZC=F", "ZW=F", "KC=F"):
        assert comm in items
        assert items[comm]["group"] == "commodities", (comm, items[comm]["group"])

    required_tfs = {"1m", "5m", "15m", "1H", "4H", "1D"}
    for sym, it in items.items():
        missing = required_tfs - set(it["intervals"])
        assert not missing, f"{sym} missing timeframes: {missing}"


def test_series_accepts_lowercase_1h_and_4h(client, monkeypatch):
    c, h = client
    monkeypatch.setenv("TWELVEDATA_API_KEY", "mock-td-key")
    seen_intervals: list[str] = []

    def _capture(requested, symbol, start, end, interval="1D", user_id=None, **kw):
        seen_intervals.append(interval)
        return _FakeProv(), _result()

    monkeypatch.setattr(market, "fetch_bars", _capture)
    for raw_iv, expected_iv in (("1m", "1m"), ("5m", "5m"), ("15m", "15m"), ("1h", "1H"), ("4h", "4H")):
        r = c.get(f"/api/v1/market/series?symbol=EURUSD&interval={raw_iv}&days=5", headers=h)
        assert r.status_code == 200, (raw_iv, r.text)
        assert r.json()["interval"] == expected_iv
    assert seen_intervals == ["1m", "5m", "15m", "1H", "4H"]


def test_polygon_spot_metal_symbol_mapping():
    from app.data_providers.polygon import PolygonProvider

    p = PolygonProvider()
    assert "commodity" in p.capabilities.asset_classes
    assert p._polygon_symbol("XAU/USD") == "C:XAUUSD"
    assert p._polygon_symbol("XAG/USD") == "C:XAGUSD"
    assert p._polygon_symbol("EUR/USD") == "C:EURUSD"
    assert p._polygon_symbol("EURUSD") == "C:EURUSD"
    assert p._polygon_symbol("BTC/USD") == "X:BTCUSD"
    assert p._polygon_symbol("BTC-USD") == "X:BTCUSD"


def test_yfinance_supports_all_intraday_and_clamps_lookback():
    import datetime as dt
    from app.data_providers.yfinance_provider import YFinanceProvider

    yf_p = YFinanceProvider()
    for iv in ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"):
        assert iv in yf_p.intervals
        assert iv in yf_p.capabilities.timeframes

    today = dt.datetime.now(dt.UTC).date()
    too_old = (today - dt.timedelta(days=30)).isoformat()
    clamped = yf_p._clamp_intraday_start(too_old, today.isoformat(), "1m")
    assert (today - dt.date.fromisoformat(clamped)).days <= 7


def test_twelvedata_batch_error_item_not_cached_as_zero(monkeypatch):
    from app.data_providers import twelvedata as td_mod

    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    with td_mod._quote_lock:
        td_mod._quote_cache.clear()
        td_mod._quote_errors.clear()
        td_mod._quote_rate_limited_until = 0.0

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "XAU/USD": {
                    "symbol": "XAU/USD",
                    "close": "3537.25",
                    "previous_close": "3520.00",
                    "is_market_open": True,
                    "datetime": "2026-11-22 13:00:00",
                },
                "XAG/USD": {
                    "code": 403,
                    "message": "**symbol** XAG/USD is not available with your plan.",
                    "status": "error",
                },
            }

    class _Client:
        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(td_mod, "get_httpx_client", lambda *a, **k: _Client())

    p = td_mod.TwelveDataProvider()
    out = p.fetch_quotes_batch(["XAU/USD", "XAG/USD"])
    assert "XAU/USD" in out
    assert out["XAU/USD"]["price"] == pytest.approx(3537.25)
    assert "XAG/USD" not in out  # must never cache bogus 0.0 price

    with pytest.raises(ProviderError) as exc:
        p.fetch_quote("XAG/USD")
    assert exc.value.code == "PROVIDER_NOT_ENTITLED"

    with td_mod._quote_lock:
        td_mod._quote_cache.clear()
        td_mod._quote_errors.clear()
        td_mod._quote_rate_limited_until = 0.0
