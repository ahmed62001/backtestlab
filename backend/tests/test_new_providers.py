"""Phase 3 tests for newly added providers.

All HTTP calls are mocked with respx. The session-wide conftest socket guard
blocks accidental live sockets independently of these interceptors.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

import pytest
import respx
from app.data_providers.base import (
    ERR_NOT_CONFIGURED,
    ERR_RATE_LIMITED,
    ERR_UNKNOWN_SYMBOL,
    ERR_UPSTREAM_UNAVAILABLE,
    ProviderError,
)
from httpx import Response


@pytest.fixture(autouse=True)
def no_provider_backoff(monkeypatch):
    """Keep retry-path tests fast without changing production defaults."""
    monkeypatch.setattr("app.data_providers.base.RETRY_BACKOFF_S", 0.0)


# ---------------------------------------------------------------- CoinGecko
@respx.mock
def test_coingecko_success_is_normalized():
    from app.data_providers.coingecko import CoingeckoProvider

    route = respx.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range").mock(
        return_value=Response(
            200,
            json={
                "prices": [
                    [1_650_000_000_000, 18_000.0],
                    [1_650_086_400_000, 18_100.0],
                    [1_650_172_800_000, 17_950.0],
                ],
                "total_volumes": [
                    [1_650_000_000_000, 12.0],
                    [1_650_086_400_000, 13.0],
                    [1_650_172_800_000, 11.0],
                ],
            },
        ),
    )
    frame = CoingeckoProvider().fetch_ohlcv("BTC-USD", "2022-04-13", "2022-04-17")
    assert route.called
    # The request must ask for the *requested* window, not a fixed lookback.
    params = route.calls[0].request.url.params
    assert params["vs_currency"] == "usd"
    assert int(params["from"]) == 1_649_808_000  # 2022-04-13T00:00:00Z
    assert int(params["to"]) == 1_650_153_600  # 2022-04-17T00:00:00Z
    assert len(frame) >= 2  # at least 2 bars should survive date filtering
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert str(frame.index.tz) == "UTC"
    assert frame["volume"].tolist()[:2] == [12.0, 13.0]


@respx.mock
def test_coingecko_empty_range_is_no_data_and_not_retried():
    """A reachable 200 with no prices is a permanent PROVIDER_NO_DATA (422).

    Regression: the old provider asked for the last 365 days and filtered by
    the requested historical window, producing an empty frame that was retried
    three times and surfaced as a misleading 404.
    """
    from app.data_providers.coingecko import CoingeckoProvider

    route = respx.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range").mock(
        return_value=Response(200, json={"prices": [], "total_volumes": []})
    )
    with pytest.raises(ProviderError) as exc:
        CoingeckoProvider().fetch_ohlcv("BTC-USD", "2014-01-01", "2014-01-10")
    assert exc.value.code == "PROVIDER_NO_DATA"
    assert route.call_count == 1


def test_coingecko_rejects_bad_symbol_without_http():
    from app.data_providers.coingecko import CoingeckoProvider

    with pytest.raises(ProviderError) as exc:
        CoingeckoProvider().fetch_ohlcv("NOT_A_PAIR", "2022-01-01", "2022-01-02")
    assert exc.value.code == ERR_UNKNOWN_SYMBOL


@respx.mock
def test_coingecko_maps_http_503_to_upstream_unavailable():
    from app.data_providers.coingecko import CoingeckoProvider

    respx.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range").mock(
        return_value=Response(503, json={"error": "maintenance"})
    )
    with pytest.raises(ProviderError) as exc:
        CoingeckoProvider().fetch_ohlcv("BTC-USD", "2022-04-13", "2022-04-17")
    assert exc.value.code == ERR_UPSTREAM_UNAVAILABLE


# -------------------------------------------------------------- Frankfurter
@respx.mock
def test_frankfurter_success_is_normalized():
    from app.data_providers.frankfurter import FrankfurterProvider

    route = respx.get("https://api.frankfurter.dev/v1/2022-04-14..2022-04-15").mock(
        return_value=Response(
            200,
            json={
                "base": "EUR",
                "rates": {"2022-04-14": {"USD": 1.08}, "2022-04-15": {"USD": 1.09}},
            },
        ),
    )
    # The documented API response is rates: {date: {quote: rate}}. Provider
    # accepts the legacy scalar fixture too, so test the production shape.
    frame = FrankfurterProvider().fetch_ohlcv("EURUSD", "2022-04-14", "2022-04-15")
    assert route.called
    assert len(frame) == 2
    assert frame["close"].tolist() == [1.08, 1.09]
    assert (frame["volume"] == 0.0).all()


def test_frankfurter_rejects_bad_pair_without_http():
    from app.data_providers.frankfurter import FrankfurterProvider

    with pytest.raises(ProviderError) as exc:
        FrankfurterProvider().fetch_ohlcv("INVALID", "2022-01-01", "2022-01-02")
    assert exc.value.code == ERR_UNKNOWN_SYMBOL


# ---------------------------------------------------------- Key-gated HTTP
@pytest.mark.parametrize(
    ("module_name", "class_name", "env_name", "symbol"),
    [
        ("app.data_providers.fred", "FredProvider", "FRED_API_KEY", "GDP"),
        ("app.data_providers.twelvedata", "TwelveDataProvider", "TWELVEDATA_API_KEY", "AAPL"),
        ("app.data_providers.polygon", "PolygonProvider", "POLYGON_API_KEY", "AAPL"),
    ],
)
def test_key_gated_provider_rejects_missing_key(
    monkeypatch, module_name, class_name, env_name, symbol
):
    module = __import__(module_name, fromlist=[class_name])
    provider = getattr(module, class_name)()
    monkeypatch.delenv(env_name, raising=False)
    assert provider.health_check()["available"] is False
    with pytest.raises(ProviderError) as exc:
        provider.fetch_ohlcv(symbol, "2022-01-01", "2022-01-05")
    assert exc.value.code == ERR_NOT_CONFIGURED


# --------------------------------------------------------------------- FRED
@respx.mock
def test_fred_success_skips_missing_observations(monkeypatch):
    from app.data_providers.fred import FredProvider

    monkeypatch.setenv("FRED_API_KEY", "test-key")
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=Response(
            200,
            json={
                "observations": [
                    {"date": "2022-01-01", "value": "21012"},
                    {"date": "2022-01-02", "value": "."},
                    {"date": "2022-01-03", "value": "21100"},
                ]
            },
        ),
    )
    frame = FredProvider().fetch_ohlcv("GDP", "2022-01-01", "2022-01-03")
    assert route.called
    assert len(frame) == 2
    assert frame["close"].tolist() == [21012.0, 21100.0]
    assert (frame["volume"] == 0.0).all()


# --------------------------------------------------------------- TwelveData
@respx.mock
def test_twelvedata_success_is_normalized(monkeypatch):
    from app.data_providers.twelvedata import TwelveDataProvider

    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    route = respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=Response(
            200,
            json={
                "values": [
                    {
                        "datetime": "2022-01-03 00:00:00",
                        "open": "150",
                        "high": "152",
                        "low": "149",
                        "close": "151",
                        "volume": "1000",
                    },
                    {
                        "datetime": "2022-01-04 00:00:00",
                        "open": "151",
                        "high": "155",
                        "low": "150",
                        "close": "154",
                        "volume": "1200",
                    },
                ]
            },
        ),
    )
    frame = TwelveDataProvider().fetch_ohlcv("AAPL", "2022-01-01", "2022-01-05")
    assert route.called
    assert len(frame) == 2
    assert frame["close"].tolist() == [151.0, 154.0]


@respx.mock
def test_twelvedata_maps_rate_limit(monkeypatch):
    from app.data_providers.twelvedata import TwelveDataProvider

    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=Response(200, json={"status": "error", "message": "rate limit exceeded"})
    )
    with pytest.raises(ProviderError) as exc:
        TwelveDataProvider().fetch_ohlcv("AAPL", "2022-01-01", "2022-01-05")
    assert exc.value.code == ERR_RATE_LIMITED


# ------------------------------------------------------------------ Polygon
@respx.mock
def test_polygon_success_is_normalized(monkeypatch):
    from app.data_providers.polygon import PolygonProvider

    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    route = respx.get(
        "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2022-01-01/2022-01-05"
    ).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {"t": 1_641_168_000_000, "o": 150, "h": 152, "l": 149, "c": 151, "v": 1000},
                    {"t": 1_641_254_400_000, "o": 151, "h": 155, "l": 150, "c": 154, "v": 1200},
                ]
            },
        ),
    )
    frame = PolygonProvider().fetch_ohlcv("AAPL", "2022-01-01", "2022-01-05")
    assert route.called
    assert len(frame) == 2
    assert frame["close"].tolist() == [151.0, 154.0]


@respx.mock
def test_polygon_maps_rate_limit(monkeypatch):
    from app.data_providers.polygon import PolygonProvider

    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    respx.get("https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2022-01-01/2022-01-05").mock(
        return_value=Response(200, json={"status": "ERROR", "error": "rate limit exceeded"})
    )
    with pytest.raises(ProviderError) as exc:
        PolygonProvider().fetch_ohlcv("AAPL", "2022-01-01", "2022-01-05")
    assert exc.value.code == ERR_RATE_LIMITED


# ---------------------------------------------------------- Vendor adapters
def test_binance_public_vendor_adapter_metadata():
    from app.data_providers.binance_public import BinancePublicProvider

    provider = BinancePublicProvider()
    assert provider.id == "binance_public"
    assert provider.requires_key is False
    assert provider.capabilities.category == "crypto"
    assert "1H" in provider.intervals
    health = provider.health_check()
    assert {"available", "detail"} <= set(health)


def test_tiingo_vendor_adapter_metadata():
    from app.data_providers.tiingo import TiingoProvider

    provider = TiingoProvider()
    assert provider.id == "tiingo"
    assert provider.requires_key is True
    assert provider.adjusted is True
    assert provider.capabilities.category == "equities"
    assert provider.capabilities.requires_key_env == "TIINGO_API_KEY"


# ------------------------------------------------------------------ Catalog
def test_catalog_includes_new_provider_capabilities():
    from app.data_providers.registry import provider_infos

    catalog = provider_infos()
    by_id = {item["id"]: item for item in catalog["items"]}
    expected_categories = {
        "binance_public": "crypto",
        "coingecko": "crypto",
        "frankfurter": "fx",
        "fred": "macro",
        "tiingo": "equities",
        "twelvedata": "equities",
        "polygon": "equities",
    }
    for provider_id, category in expected_categories.items():
        item = by_id[provider_id]
        assert item["category"] == category
        assert item["assetClasses"]
        assert item["rateLimitPerMinute"] > 0
        assert item["descriptionEn"] and item["descriptionAr"]

    assert by_id["fred"]["requiresKeyEnv"] == "FRED_API_KEY"
    assert by_id["twelvedata"]["requiresKeyEnv"] == "TWELVEDATA_API_KEY"
    assert by_id["polygon"]["requiresKeyEnv"] == "MASSIVE_API_KEY"
    assert by_id["polygon"]["requiresKeyEnvLegacy"] == "POLYGON_API_KEY"


def test_all_new_providers_are_registered_and_enabled():
    from app.data_providers.registry import _ALL, enabled_ids

    expected = {
        "binance_public",
        "coingecko",
        "frankfurter",
        "fred",
        "tiingo",
        "twelvedata",
        "polygon",
    }
    assert expected <= set(_ALL)
    assert expected <= set(enabled_ids())
