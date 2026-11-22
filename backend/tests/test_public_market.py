"""Public (pre-login) market endpoints.

These tests use a deterministic fixture frame (labelled fixture, never live)
and the real public endpoint code path. No network is allowed by conftest.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_test.db")

import app.market as market  # noqa: E402
from app.data_providers.base import BarsResult, ProviderError  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clear_public_state():
    market._public_cache.clear()
    market._public_rate.clear()
    market._public_key_locks.clear()
    yield
    market._public_cache.clear()
    market._public_rate.clear()
    market._public_key_locks.clear()


def _frame():
    import pandas as pd

    idx = pd.date_range("2026-11-10", periods=3, freq="D", tz="UTC")
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
    return BarsResult(
        frame=_frame(),
        provenance={"provider": provider_id, "fetched_at": "2026-11-16T00:00:00+00:00"},
    )


class _FakeProv:
    id = "twelvedata"
    intervals = ("1D", "1H", "1W", "1M")


def test_public_instruments_requires_no_auth(client):
    r = client.get("/api/v1/public/market/instruments")
    assert r.status_code == 200, r.text
    body = r.json()
    symbols = {it["symbol"] for it in body["items"]}
    assert {"AAPL", "BTC-USD"} <= symbols
    # FX has no credential-free OHLCV provider and must not be advertised.
    assert "EURUSD" not in symbols
    assert body["defaultSymbol"] in symbols
    assert body["provider"] == "twelvedata"


def test_public_series_requires_no_auth_and_returns_contract(client, monkeypatch):
    monkeypatch.setattr(market, "fetch_bars", lambda *a, **k: (_FakeProv(), _result()))
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D&limit=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "AAPL"
    assert body["displayName"]
    assert body["assetClass"] == "equity"
    assert body["interval"] == "1D"
    assert body["provider"] == "twelvedata"
    assert body["dataStatus"] in ("delayed", "cached", "live", "stale")
    assert body["retrievedAt"]
    assert body["lastCandleTime"] == body["candles"][-1]["t"]
    assert len(body["candles"]) == 2  # limit applied
    for c in body["candles"]:
        assert {"t", "o", "h", "l", "c", "v"} <= set(c)
        assert c["l"] <= min(c["o"], c["c"])
        assert c["h"] >= max(c["o"], c["c"])
        assert c["v"] >= 0


def test_public_series_rejects_unknown_symbol(client):
    r = client.get("/api/v1/public/market/series?symbol=NOPE123&interval=1D")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "UNKNOWN_SYMBOL"
    assert body["retryable"] is False


def test_public_series_rejects_bad_interval(client):
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=5m")
    assert r.status_code == 400
    assert r.json()["code"] == "BAD_INTERVAL"


def test_public_series_rejects_bad_limit(client):
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D&limit=99999")
    assert r.status_code == 400
    assert r.json()["code"] == "BAD_LIMIT"


def test_public_series_maps_provider_failure(client, monkeypatch):
    def boom(*a, **k):
        raise ProviderError("twelvedata", "UPSTREAM_UNAVAILABLE", "twelvedata: upstream down")

    monkeypatch.setattr(market, "fetch_bars", boom)
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["code"] == "UPSTREAM_UNAVAILABLE"
    assert body["retryable"] is True


def test_public_series_serves_bounded_stale_after_failure(client, monkeypatch):
    monkeypatch.setattr(market, "fetch_bars", lambda *a, **k: (_FakeProv(), _result()))
    first = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert first.status_code == 200

    # Age the cache past its TTL but inside the stale window for 1D.
    key = ("AAPL", "1D")
    stored_at, payload = market._public_cache[key]
    market._public_cache[key] = (stored_at - 400, payload)

    def boom(*a, **k):
        raise ProviderError("twelvedata", "UPSTREAM_UNAVAILABLE", "twelvedata: upstream down")

    monkeypatch.setattr(market, "fetch_bars", boom)
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataStatus"] == "stale"
    assert body["staleSince"]
    assert body["cacheAgeSeconds"] >= 400


def test_public_series_rejects_inconsistent_candles(client, monkeypatch):
    bad = _frame()
    bad.loc[bad.index[-1], "high"] = 1.0  # high below close

    def inconsistent(*a, **k):
        return _FakeProv(), BarsResult(frame=bad, provenance={"provider": "twelvedata"})

    monkeypatch.setattr(market, "fetch_bars", inconsistent)
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code == 502
    assert r.json()["code"] == "INVALID_CANDLES"


def test_public_series_rate_limit(client, monkeypatch):
    monkeypatch.setattr(market, "_PUBLIC_RATE_MAX", 1)
    monkeypatch.setattr(market, "fetch_bars", lambda *a, **k: (_FakeProv(), _result()))
    first = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert first.status_code == 200
    second = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"
    assert second.json()["retryable"] is True
    assert second.headers.get("Retry-After")


def test_private_market_and_backtest_endpoints_still_require_auth(client):
    for path in ("/api/v1/market/series?symbol=AAPL", "/api/v1/backtests"):
        r = client.get(path)
        assert r.status_code == 401, (path, r.status_code, r.text)
