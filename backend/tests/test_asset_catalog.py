"""Phase 6: the API asset catalog is registry-driven and eligibility-correct."""

from __future__ import annotations

import pytest


def _catalog_by_ticker():
    from app.instruments import asset_catalog

    return {item["ticker"]: item for item in asset_catalog()}


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch):
    for name in (
        "ALPHAVANTAGE_API_KEY",
        "FRED_API_KEY",
        "TIINGO_API_KEY",
        "TWELVEDATA_API_KEY",
        "POLYGON_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_crypto_assets_are_visible_with_correct_providers():
    items = _catalog_by_ticker()
    for symbol in ("BTC-USD", "ETH-USD", "BTC-USDT", "ETH-USDT"):
        assert symbol in items, symbol
        assert items[symbol]["assetClass"] == "crypto"
        assert items[symbol]["market"] == "Crypto"
        assert items[symbol]["nameKey"] in ("assets.btc", "assets.eth")

    # Quote-currency safety: yfinance maps USDT to USD and is not a valid
    # source for a USDT-quoted instrument.
    assert "yfinance" not in items["BTC-USDT"]["providers"]
    assert "binance_public" in items["BTC-USDT"]["providers"]
    assert "yfinance" in items["BTC-USD"]["providers"]


def test_macro_and_unconfigured_fx_are_not_tradable_assets():
    items = _catalog_by_ticker()
    assert "FRED:GDP" not in items
    assert "FRED:CPI" not in items
    assert "EURUSD" not in items
    assert "GBPUSD" not in items
    assert "USDJPY" not in items
    assert all(v["assetClass"] != "macro_reference" for v in items.values())


def test_fx_appears_only_when_a_real_ohlcv_provider_is_configured(monkeypatch):
    assert "EURUSD" not in _catalog_by_ticker()

    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key-not-used-for-network")
    items = _catalog_by_ticker()
    assert "EURUSD" in items
    assert items["EURUSD"]["assetClass"] == "fx"
    assert items["EURUSD"]["providers"] == ["twelvedata"]
    # The reference-rate provider must never appear as an FX OHLCV source.
    assert "frankfurter" not in items["EURUSD"]["providers"]


def test_assets_endpoint_keeps_frontend_contract():
    from app.main import create_app
    from fastapi.testclient import TestClient

    c = TestClient(create_app(), raise_server_exceptions=False)
    r = c.get("/api/v1/assets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(body["items"])
    assert body["items"]
    for item in body["items"]:
        assert {"ticker", "nameKey", "market", "halalScreened"} <= set(item)
        assert {"assetClass", "providers", "timeframes"} <= set(item)
        assert item["providers"], item
