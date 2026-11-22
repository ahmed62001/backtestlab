"""Deterministic crypto API -> worker -> engine -> database end-to-end tests.

The provider boundary is replaced with a recorded/deterministic frame, so the
suite never touches the network. Live Binance/CCXT connectivity is deliberately
kept in ``scripts/smoke_providers.py`` and is not asserted here.
"""

from __future__ import annotations

import math
import time
import uuid

import pandas as pd
import pytest


def _deterministic_bars(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Deterministic daily OHLCV fixture for a crypto pair."""
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    if len(idx) == 0:
        idx = pd.date_range("2022-01-01", periods=365, freq="D", tz="UTC")
    base = 30000.0 if symbol.startswith("BTC") else 2000.0
    rows = []
    for i, _ts in enumerate(idx):
        drift = 1.0 + 0.0004 * i + 0.08 * math.sin(i / 17.0)
        close = base * drift
        open_ = close * (1.0 + 0.002 * math.sin(i / 5.0))
        high = max(open_, close) * 1.004
        low = min(open_, close) * 0.996
        rows.append((open_, high, low, close, 1000.0 + i))
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


def _client():
    from app.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app(), raise_server_exceptions=False)


def _register(c, email: str):
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Crypto E2E", "email": email, "password": "password123"},
    )
    if r.status_code != 201:
        r = c.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
    assert r.status_code in (200, 201), r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _body(symbol: str, provider: str = "binance_public") -> dict:
    return {
        "templateId": "buy-hold",
        "asset": symbol,
        "from": "2022-01-01",
        "to": "2022-12-31",
        "initialCapital": 10000,
        "feePct": 0.1,
        "interval": "1D",
        "params": {},
        "dataProvider": provider,
    }


@pytest.mark.parametrize(
    ("requested", "canonical", "quote"),
    [
        ("BTC/USDT", "BTC-USDT", "USDT"),
        ("ETH/USDT", "ETH-USDT", "USDT"),
    ],
)
def test_crypto_api_worker_database_e2e(monkeypatch, tmp_path, requested, canonical, quote):
    import app.data_providers.base as base_mod
    import app.data_providers.registry as reg
    from app.data_providers.binance_public import BinancePublicProvider

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(reg, "FALLBACK_ENABLED", False)

    def fake_fetch(self, symbol, start, end, interval="1D"):
        return _deterministic_bars(symbol, start, end)

    monkeypatch.setattr(BinancePublicProvider, "fetch_ohlcv_raw", fake_fetch)

    c = _client()
    h = _register(c, f"crypto-{uuid.uuid4().hex[:12]}@t.com")

    r = c.post("/api/v1/backtests?async=true", json=_body(requested), headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    jid = out["jobId"]
    bid = out["backtestId"]

    status = ""
    deadline = time.time() + 25
    while time.time() < deadline:
        jr = c.get(f"/api/v1/jobs/{jid}", headers=h)
        assert jr.status_code == 200, jr.text
        job = jr.json()
        status = job["status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.05)
    assert status == "done", job

    d = c.get(f"/api/v1/backtests/{bid}", headers=h)
    assert d.status_code == 200, d.text
    result = d.json()
    assert result["status"] == "done"
    assert result["asset"] == canonical
    assert result["engine"]["mode"] == "vendor"
    assert result["equity"], "engine produced no equity curve"
    assert isinstance(result["trades"], int)

    pv = result["provenance"]
    assert pv["provider"] == "binance_public"
    assert pv["requested_provider"] == "binance_public"
    assert pv["symbol"] == canonical
    assert pv["requested_symbol"] == requested
    assert pv["asset_class"] == "crypto"
    assert pv["base_currency"] == canonical.split("-")[0]
    assert pv["quote_currency"] == quote
    assert pv["market_type"] == "spot"
    assert pv["interval"] == "1D"
    assert pv["fallback"] is False
    assert pv["price_adjustment"] == "unadjusted"
    assert pv["dataHash"] and len(pv["dataHash"]) == 64
    assert pv["requested_start"] == "2022-01-01"
    assert pv["requested_end"] == "2022-12-31"
    assert pv["start"] and pv["end"]
    assert pv["retrieved_at"]

    # The summary/list view also carries the actual provider.
    listed = c.get("/api/v1/backtests", headers=h).json()
    assert any(
        item["id"] == bid and item["dataProvider"] == "binance_public" for item in listed["items"]
    )


def test_crypto_invalid_instruments_and_provider_combinations_are_rejected(monkeypatch):
    import app.data_providers.registry as reg

    monkeypatch.setattr(reg, "FALLBACK_ENABLED", False)
    c = _client()
    h = _register(c, f"crypto-bad-{uuid.uuid4().hex[:12]}@t.com")

    cases = [
        (_body("BTC/XYZ"), "UNKNOWN_ASSET"),
        (_body("BTC-USDT", "stooq"), "BAD_INPUT"),
        (_body("BTC-USDT", "yfinance"), "BAD_INPUT"),  # USD blend is forbidden
        (_body("AAPL", "binance_public"), "BAD_INPUT"),
        (_body("EURUSD", "twelvedata"), "ASSET_NOT_BACKTESTABLE"),
        (_body("FRED:GDP", "fred"), "ASSET_NOT_BACKTESTABLE"),
    ]
    for body, expected_code in cases:
        r = c.post("/api/v1/backtests", json=body, headers=h)
        assert r.status_code == 422, (body, r.status_code, r.text)
        assert r.json()["code"] == expected_code, (body, r.json())
