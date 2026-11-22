"""Unit tests for TwelveData, Massive (formerly Polygon.io), and FRED remediations."""

from __future__ import annotations

import os
import pathlib
import sys

import httpx
import pytest
import respx

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_test.db")

from app.data_providers.base import (  # noqa: E402
    ERR_INVALID_KEY,
    ERR_NOT_CONFIGURED,
    ERR_NOT_ENTITLED,
    ProviderError,
    clear_httpx_clients,
)
from app.data_providers.fred import FredProvider  # noqa: E402
from app.data_providers.polygon import PolygonProvider  # noqa: E402
from app.data_providers.twelvedata import TwelveDataProvider  # noqa: E402
from app.instruments import _provider_configured  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_clients():
    clear_httpx_clients()
    yield
    clear_httpx_clients()


def test_massive_key_precedence_and_placeholders(monkeypatch):
    p = PolygonProvider()
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    assert p._resolve_key() == ""
    assert not _provider_configured("polygon")

    # Placeholder in MASSIVE_API_KEY must not shadow real POLYGON_API_KEY
    monkeypatch.setenv("MASSIVE_API_KEY", "your_massive_api_key")
    monkeypatch.setenv("POLYGON_API_KEY", "legacy-real-key-12345")
    assert p._resolve_key() == "legacy-real-key-12345"
    assert _provider_configured("polygon")

    # Real MASSIVE_API_KEY wins over POLYGON_API_KEY
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-real-key-67890")
    assert p._resolve_key() == "massive-real-key-67890"
    assert "Massive" in p.name_en
    assert "Polygon.io" in p.name_en
    assert p.capabilities.requires_key_env == "MASSIVE_API_KEY"
    assert p.capabilities.requires_key_env_legacy == "POLYGON_API_KEY"


@respx.mock
def test_massive_bearer_auth_and_pagination(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "ms-test-secret-key")
    p = PolygonProvider()
    base_url = "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2026-01-01/2026-01-05"
    page2_url = f"{base_url}?cursor=abc"

    calls = {"n": 0}

    def _dispatch(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "results": [
                        {"t": 1767225600000, "o": 100, "h": 102, "l": 99, "c": 101, "v": 1000}
                    ],
                    "next_url": page2_url,
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {"t": 1767312000000, "o": 101, "h": 104, "l": 100, "c": 103, "v": 1200}
                ],
            },
        )

    route = respx.get(base_url).mock(side_effect=_dispatch)

    df = p.fetch_ohlcv_raw("AAPL", "2026-01-01", "2026-01-05", "1D")
    assert len(df) == 2
    assert route.call_count == 2
    assert route.calls[0].request.headers.get("Authorization") == "Bearer ms-test-secret-key"
    assert "apiKey=" not in str(route.calls[0].request.url)
    assert route.calls[1].request.headers.get("Authorization") == "Bearer ms-test-secret-key"


@respx.mock
def test_massive_distinguishes_401_and_403(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "ms-test-key")
    p = PolygonProvider()
    url = "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2026-01-01/2026-01-05"

    respx.get(url).mock(return_value=httpx.Response(401, json={"status": "ERROR"}))
    with pytest.raises(ProviderError) as exc1:
        p.fetch_ohlcv_raw("AAPL", "2026-01-01", "2026-01-05", "1D")
    assert exc1.value.code == ERR_INVALID_KEY

    respx.get(url).mock(return_value=httpx.Response(403, json={"status": "NOT_AUTHORIZED"}))
    with pytest.raises(ProviderError) as exc2:
        p.fetch_ohlcv_raw("AAPL", "2026-01-01", "2026-01-05", "1D")
    assert exc2.value.code == ERR_NOT_ENTITLED


@respx.mock
def test_twelvedata_uses_header_auth_and_classifies_errors(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "td-test-secret")
    p = TwelveDataProvider()
    route = respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {
                        "datetime": "2026-01-02",
                        "open": "100",
                        "high": "102",
                        "low": "99",
                        "close": "101",
                        "volume": "5000",
                    }
                ],
            },
        )
    )
    df = p.fetch_ohlcv_raw("AAPL", "2026-01-01", "2026-01-03", "1D")
    assert len(df) == 1
    req = route.calls[0].request
    assert req.headers.get("Authorization") == "apikey td-test-secret"
    assert "apikey=" not in str(req.url)

    # Plan restriction -> ERR_NOT_ENTITLED
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(
            200,
            json={"status": "error", "code": 403, "message": "Available with Grow plan"},
        )
    )
    with pytest.raises(ProviderError) as exc:
        p.fetch_ohlcv_raw("AAPL", "2026-01-01", "2026-01-03", "1D")
    assert exc.value.code == ERR_NOT_ENTITLED


@respx.mock
def test_fred_macro_observations_preserves_missing_and_metadata(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fred-test-key")
    p = FredProvider()
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-01-01", "value": "3.8"},
                    {"date": "2026-02-01", "value": "."},
                    {"date": "2026-03-01", "value": "3.9"},
                ]
            },
        )
    )
    respx.get("https://api.stlouisfed.org/fred/series").mock(
        return_value=httpx.Response(
            200,
            json={
                "seriess": [
                    {
                        "id": "UNRATE",
                        "title": "Unemployment Rate",
                        "units": "Percent",
                        "units_short": "%",
                        "frequency": "Monthly",
                        "frequency_short": "M",
                        "seasonal_adjustment": "Seasonally Adjusted",
                        "last_updated": "2026-04-03 07:45:00-05",
                    }
                ]
            },
        )
    )

    out = p.fetch_macro_observations("UNRATE", start="2026-01-01", end="2026-03-01")
    assert out["seriesId"] == "UNRATE"
    assert out["dataType"] == "macroeconomic_observations"
    assert out["backtestEligible"] is False
    assert out["frequencyShort"] == "M"
    assert out["units"] == "Percent"
    assert out["count"] == 3
    assert out["validCount"] == 2
    assert out["observations"][1] == {"date": "2026-02-01", "value": None, "missing": True}


def test_macro_endpoint_requires_auth_and_rejects_macro_backtest(monkeypatch):
    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/api/v1/macro/series?series_id=GDP").status_code == 401

    r = c.post(
        "/api/v1/auth/register",
        json={"name": "MacroQA", "email": "macro_qa@t.com", "password": "password123"},
    )
    if r.status_code == 201:
        tok = r.json()["token"]
    else:
        tok = c.post(
            "/api/v1/auth/login",
            json={"email": "macro_qa@t.com", "password": "password123"},
        ).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}

    # Macro series cannot be used as an ordinary OHLCV backtest asset
    bt = c.post(
        "/api/v1/backtests",
        headers=hdr,
        json={
            "name": "Macro test",
            "asset": "FRED:GDP",
            "template": "sma_crossover",
            "params": {"fast": 10, "slow": 30},
            "startDate": "2024-01-01",
            "endDate": "2025-01-01",
            "initialCapital": 10000,
            "feeBps": 5,
            "slippageBps": 2,
            "dataProvider": "fred",
        },
    )
    assert bt.status_code == 422
    body = bt.json()
    code = body.get("code") or (body.get("detail") or body.get("error") or {}).get("code")
    assert code == "ASSET_NOT_BACKTESTABLE"

    # Unconfigured FRED returns 503 PROVIDER_NOT_CONFIGURED
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    mr = c.get("/api/v1/macro/series?series_id=GDP", headers=hdr)
    assert mr.status_code == 503
    mbody = mr.json()
    mcode = mbody.get("code") or (mbody.get("detail") or mbody.get("error") or {}).get("code")
    assert mcode == ERR_NOT_CONFIGURED
