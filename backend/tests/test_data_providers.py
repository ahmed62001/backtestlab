"""Phase 2 gates: data providers (interface, registry, cache, errors, API).

No live network: vendor loader HTTP is either unavailable-by-deps or
monkeypatched. Manual live checks live in scripts/smoke_providers.py.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

import pandas as pd

BASE = pathlib.Path(__file__).resolve().parent.parent


def _client():
    from app.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app(), raise_server_exceptions=False)


def _auth(c, email="dp@t.com"):
    r = c.post(
        "/api/v1/auth/register", json={"name": "DP", "email": email, "password": "password123"}
    )
    if r.status_code != 201:
        r = c.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


# ---------------------------------------------------------------- interface
def test_interface_shape_all_providers():
    from app.data_providers.registry import _ALL, enabled_ids

    for pid, cls in _ALL.items():
        p = cls()
        assert p.id == pid
        assert p.name_en and p.name_ar
        assert isinstance(p.list_supported_markets(), list)
        assert "1D" in p.intervals
        assert isinstance(p.requires_key, bool)
        h = p.health_check()
        assert {"available", "detail"} <= set(h)
        assert pid in enabled_ids()


def test_local_provider_normalization():
    from app.data_providers.local_fixtures import LocalFixturesProvider

    res = LocalFixturesProvider().fetch_ohlcv_cached("AAPL", "2022-01-01", "2022-12-31")
    df = res.frame
    assert len(df) >= 100
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing and not df.index.has_duplicates
    prov = res.provenance
    for k in (
        "provider",
        "symbol",
        "interval",
        "start",
        "end",
        "bars",
        "rows",
        "dataHash",
        "timezone",
        "adjusted",
        "license_class",
    ):
        assert k in prov, k
    assert prov["provider"] == "local"
    assert prov["dataHash"] and len(prov["dataHash"]) == 64


def test_synthetic_deterministic_and_normalized():
    from app.data_providers.synthetic import SyntheticProvider

    p = SyntheticProvider()
    a = p.fetch_ohlcv("MSFT", "2022-01-01", "2022-06-30")
    b = p.fetch_ohlcv("MSFT", "2022-01-01", "2022-06-30")
    assert a.equals(b)
    c = p.fetch_ohlcv("AAPL", "2022-01-01", "2022-06-30")
    assert not a.equals(c)  # symbol seeds differ
    assert (a["high"] >= a[["open", "close"]].max(axis=1) - 1e-9).all()


# ---------------------------------------------------------------- csv_upload
def _csv(text: str) -> str:
    return text


GOOD_CSV = "date,open,high,low,close,volume\n" + "\n".join(
    f"2022-01-{d:02d},{100 + d},{101 + d},{99 + d},{100.5 + d},1000" for d in range(3, 20)
)


def test_csv_upload_validation_rejects_bad_files(tmp_path, monkeypatch):
    import app.data_providers.base as base_mod
    from app.data_providers.base import ProviderError
    from app.data_providers.csv_upload import validate_upload_csv

    monkeypatch.setattr(base_mod, "UPLOAD_DIR", tmp_path)
    from app.data_providers import csv_upload as cu

    monkeypatch.setattr(cu, "UPLOAD_DIR", tmp_path)
    # missing close column
    with pytest_raises(ProviderError):
        validate_upload_csv(b"date,open,high,low\n2022-01-03,1,2,0.5", "TEST")
    # unsorted dates
    bad = "date,open,high,low,close,volume\n2022-01-05,1,2,0.5,1.5,10\n2022-01-03,1,2,0.5,1.5,10\n"
    with pytest_raises(ProviderError):
        validate_upload_csv(bad.encode(), "TEST")
    # duplicate dates
    dup = "date,open,high,low,close,volume\n2022-01-03,1,2,0.5,1.5,10\n2022-01-03,1,2,0.5,1.5,10\n"
    with pytest_raises(ProviderError):
        validate_upload_csv(dup.encode(), "TEST")
    # size limit
    huge = ("date,open,high,low,close,volume\n" + "2022-01-03,1,2,0.5,1.5,10\n" * 300000).encode()
    with pytest_raises(ProviderError):
        validate_upload_csv(huge, "TEST")
    # bad symbol
    with pytest_raises(ProviderError):
        validate_upload_csv(GOOD_CSV.encode(), "BAD SYM!")


def pytest_raises(exc):
    import pytest

    return pytest.raises(exc)


def test_csv_upload_roundtrip(tmp_path, monkeypatch):
    from app.data_providers import csv_upload as cu

    monkeypatch.setattr(cu, "UPLOAD_DIR", tmp_path)
    out = cu.upload_symbol_csv("upl", GOOD_CSV.encode(), "user-a")
    assert out["rows"] == 17
    df = cu.CsvUploadProvider(user_id="user-a").fetch_ohlcv("UPL", "2022-01-01", "2022-12-31")
    assert len(df) == 17 and str(df.index.tz) == "UTC"
    # Per-user namespace: another tenant sees no file and cannot overwrite it.
    from app.data_providers.base import ProviderError

    with pytest.raises(ProviderError) as exc:
        cu.CsvUploadProvider(user_id="user-b").fetch_ohlcv("UPL", "2022-01-01", "2022-12-31")
    assert exc.value.code == "UNKNOWN_SYMBOL"
    assert out["path"] == f"{cu.user_scope('user-a')}/UPL.csv"
    assert "user-a" not in out["path"]


import pytest


# ------------------------------------------------------- vendor adapters
def _fake_frame(idx):
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(len(idx))],
            "high": [101.0 + i for i in range(len(idx))],
            "low": [99.0 + i for i in range(len(idx))],
            "close": [100.5 + i for i in range(len(idx))],
            "volume": [1000.0] * len(idx),
        },
        index=idx,
    )


def test_stooq_adapter_normalization(monkeypatch):
    from app.data_providers import vendor_shim
    from app.data_providers.stooq import StooqProvider

    idx = pd.date_range("2022-01-03", periods=5, name="trade_date")

    class FakeLoader:
        def is_available(self):
            return True

        def fetch(self, codes, start, end, *, interval="1D", fields=None):
            assert codes == ["AAPL.US"], "symbol must map to stooq format"
            return {codes[0]: _fake_frame(idx)}

    monkeypatch.setattr(StooqProvider, "_loader", lambda self: FakeLoader())
    p = StooqProvider()
    assert p.health_check()["available"] is True
    res = p.fetch_ohlcv_cached("AAPL", "2022-01-01", "2022-12-31")
    assert len(res.frame) == 5 and str(res.frame.index.tz) == "UTC"
    assert res.provenance["provider"] == "stooq"
    assert res.provenance["adjusted"] is False
    del vendor_shim


def test_vendor_adapter_unknown_symbol_and_down(monkeypatch):
    from app.data_providers.base import (
        ERR_UPSTREAM_BLOCKED,
        ERR_UPSTREAM_UNAVAILABLE,
        ProviderError,
    )
    from app.data_providers.stooq import StooqProvider

    class EmptyLoader:
        def is_available(self):
            return True

        def fetch(self, codes, start, end, *, interval="1D", fields=None):
            return {}

    monkeypatch.setattr(StooqProvider, "_loader", lambda self: EmptyLoader())
    with pytest.raises(ProviderError) as ei:
        StooqProvider().fetch_ohlcv("NOPE", "2022-01-01", "2022-12-31")
    # Stooq overrides no_data_code -> UPSTREAM_BLOCKED for anti-bot scenarios
    assert ei.value.code == ERR_UPSTREAM_BLOCKED
    assert "stooq" in str(ei.value)

    class DownLoader:
        def is_available(self):
            return False

        def fetch(self, *a, **k):
            raise ConnectionError("boom")

    monkeypatch.setattr(StooqProvider, "_loader", lambda self: DownLoader())
    with pytest.raises(ProviderError) as ei2:
        StooqProvider().fetch_ohlcv("AAPL.US", "2022-01-01", "2022-12-31")
    assert ei2.value.code == ERR_UPSTREAM_UNAVAILABLE
    assert "stooq" in str(ei2.value)


def test_yfinance_unavailable_without_package(monkeypatch):
    from app.data_providers.base import ProviderError
    from app.data_providers.yfinance_provider import YFinanceProvider

    monkeypatch.setattr(
        YFinanceProvider,
        "_loader",
        lambda self: (_ for _ in ()).throw(
            ProviderError("yfinance", "PROVIDER_NOT_CONFIGURED", "yfinance package not installed")
        ),
    )
    h = YFinanceProvider().health_check()
    assert h["available"] is False


def test_ccxt_unavailable_without_package(monkeypatch):
    from app.data_providers.base import ProviderError
    from app.data_providers.ccxt_provider import CcxtProvider

    monkeypatch.setattr(
        CcxtProvider,
        "_loader",
        lambda self: (_ for _ in ()).throw(
            ProviderError("ccxt", "PROVIDER_NOT_CONFIGURED", "ccxt package not installed")
        ),
    )
    assert CcxtProvider().health_check()["available"] is False


# ------------------------------------------------------- cache / retry
def test_cache_hit_miss(monkeypatch, tmp_path):
    import app.data_providers.base as base_mod
    from app.data_providers.local_fixtures import LocalFixturesProvider

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    calls = {"n": 0}
    p = LocalFixturesProvider()
    real_raw = p.fetch_ohlcv_raw

    def counting(symbol, start, end, interval="1D"):
        calls["n"] += 1
        return real_raw(symbol, start, end, interval)

    monkeypatch.setattr(p, "fetch_ohlcv_raw", counting)
    r1 = p.fetch_ohlcv_cached("AAPL", "2022-01-01", "2022-12-31")
    r2 = p.fetch_ohlcv_cached("AAPL", "2022-01-01", "2022-12-31")
    assert calls["n"] == 1, "second fetch must come from disk cache"
    assert r1.provenance["cache"] == "miss"
    assert r2.provenance["cache"] == "hit"
    assert r1.provenance["dataHash"] == r2.provenance["dataHash"]
    assert len(list(tmp_path.glob("*.csv"))) == 1


def test_retry_transient_then_success(monkeypatch):
    from app.data_providers.base import ProviderError
    from app.data_providers.local_fixtures import LocalFixturesProvider

    monkeypatch.setattr("app.data_providers.base.RETRY_BACKOFF_S", 0.0)
    p = LocalFixturesProvider()
    state = {"n": 0}
    real_raw = p.fetch_ohlcv_raw.__func__

    def flaky(self, symbol, start, end, interval="1D"):
        state["n"] += 1
        if state["n"] == 1:
            raise ProviderError(self.id, "PROVIDER_DOWN", "transient")
        return real_raw(self, symbol, start, end, interval)

    monkeypatch.setattr(LocalFixturesProvider, "fetch_ohlcv_raw", flaky)
    df = p.fetch_ohlcv("AAPL", "2022-01-01", "2022-12-31")
    assert len(df) > 0 and state["n"] == 2


# ------------------------------------------------------- network provider failure paths (mocked, offline)
def test_stooq_antibot_html_raises_clear_error(monkeypatch):
    """Stooq anti-bot (HTML challenge page) must raise a clear typed ProviderError,
    never a CSV parse crash or an empty-success frame, and never silently fall back."""
    from app.data_providers.base import ERR_UPSTREAM_BLOCKED, ProviderError
    from app.data_providers.stooq import StooqProvider

    class AntibotLoader:
        def is_available(self):
            return True

        def fetch(self, codes, start, end, *, interval="1D", fields=None):
            # Vendor loader returns an HTML anti-bot challenge page instead of CSV data.
            return {codes[0]: "<html><body>Please solve the CAPTCHA</body></html>"}

    monkeypatch.setattr(StooqProvider, "_loader", lambda self: AntibotLoader())
    p = StooqProvider()
    with pytest.raises(ProviderError) as ei:
        p.fetch_ohlcv("AAPL", "2024-01-01", "2024-06-30")
    assert ei.value.provider == "stooq"
    assert ei.value.code == ERR_UPSTREAM_BLOCKED
    assert "stooq" in str(ei.value).lower()


def test_yfinance_provider_down_mocked(monkeypatch):
    from app.data_providers.base import ERR_UPSTREAM_UNAVAILABLE, ProviderError
    from app.data_providers.yfinance_provider import YFinanceProvider

    class DownLoader:
        def is_available(self):
            return True

        def fetch(self, codes, start, end, *, interval="1D", fields=None):
            raise ConnectionError("Yahoo Finance temporary failure")

    monkeypatch.setattr(YFinanceProvider, "_loader", lambda self: DownLoader())
    with pytest.raises(ProviderError) as ei:
        YFinanceProvider().fetch_ohlcv("AAPL", "2024-01-01", "2024-06-30")
    assert ei.value.provider == "yfinance"
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE
    assert "yfinance" in str(ei.value).lower()


def test_yfinance_unknown_symbol_mocked(monkeypatch):
    from app.data_providers.base import ERR_UNKNOWN_SYMBOL, ProviderError
    from app.data_providers.yfinance_provider import YFinanceProvider

    class EmptyLoader:
        def is_available(self):
            return True

        def fetch(self, codes, start, end, *, interval="1D", fields=None):
            return {}

    monkeypatch.setattr(YFinanceProvider, "_loader", lambda self: EmptyLoader())
    with pytest.raises(ProviderError) as ei:
        YFinanceProvider().fetch_ohlcv("NOPE", "2024-01-01", "2024-06-30")
    assert ei.value.provider == "yfinance"
    assert ei.value.code == ERR_UNKNOWN_SYMBOL


def test_ccxt_timeout_mocked(monkeypatch):
    from app.data_providers.base import ERR_UPSTREAM_UNAVAILABLE, ProviderError
    from app.data_providers.ccxt_provider import CcxtProvider

    class SlowLoader:
        def is_available(self):
            return True

        def fetch(self, codes, start, end, *, interval="1D", fields=None):
            raise TimeoutError("exchange request timed out")

    monkeypatch.setattr(CcxtProvider, "_loader", lambda self: SlowLoader())
    with pytest.raises(ProviderError) as ei:
        CcxtProvider().fetch_ohlcv("BTC/USDT", "2024-01-01", "2024-06-30")
    assert ei.value.provider == "ccxt"
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE
    assert "ccxt" in str(ei.value).lower()


# ------------------------------------------------------- API contract
def test_data_providers_endpoint_contract():
    c = _client()
    r = c.get("/api/v1/data-providers")
    assert r.status_code == 200
    d = r.json()
    assert {"items", "default", "enabled"} <= set(d)
    ids = {x["id"] for x in d["items"]}
    assert {"yfinance", "stooq", "ccxt", "alphavantage", "csv_upload", "local", "synthetic"} <= ids
    for item in d["items"]:
        assert {
            "id",
            "nameEn",
            "nameAr",
            "markets",
            "intervals",
            "requiresKey",
            "available",
            "licenseClass",
            "enabled",
            "isDefault",
        } <= set(item)
    av = next(x for x in d["items"] if x["id"] == "alphavantage")
    assert av["requiresKey"] is True and av["available"] is False
    assert isinstance(av["licenseClass"], str)  # plain info, no gating


def test_backtest_rejects_unknown_or_disabled_provider():
    c = _client()
    h = _auth(c, "dpv@t.com")
    bad = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "dataProvider": "not-a-provider",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert bad.status_code == 422
    # unknown provider -> UNKNOWN_DATA_PROVIDER (documented validation code)
    assert bad.json()["code"] == "UNKNOWN_DATA_PROVIDER"
    assert "not-a-provider" in bad.json()["message"]


def test_backtest_disabled_provider_rejected(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDERS_ENABLED", "local")
    c = _client()
    h = _auth(c, "dpdis@t.com")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "dataProvider": "synthetic",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert r.status_code == 422
    # disabled provider -> UNKNOWN_DATA_PROVIDER (documented validation code)
    assert r.json()["code"] == "UNKNOWN_DATA_PROVIDER"
    assert "synthetic" in r.json()["message"]


def test_backtest_provider_failure_503_names_provider_no_synthetic(monkeypatch, tmp_path):
    import app.data_providers.base as base_mod
    from app.data_providers.base import ProviderError
    from app.data_providers.local_fixtures import LocalFixturesProvider

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)  # isolate from disk cache
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.0)

    def down(self, symbol, start, end, interval="1D"):
        raise ProviderError(self.id, "UPSTREAM_UNAVAILABLE", "simulated outage")

    monkeypatch.setattr(LocalFixturesProvider, "fetch_ohlcv_raw", down)
    c = _client()
    h = _auth(c, "dpd@t.com")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "UPSTREAM_UNAVAILABLE"
    assert "local" in body["message"]  # provider named
    # nothing stored -> the synthetic engine was NOT silently used
    assert c.get("/api/v1/backtests", headers=h).json()["total"] == 0


def test_backtest_no_data_is_422_with_context_and_not_retried(monkeypatch, tmp_path):
    """A reachable provider with zero bars is 422 PROVIDER_NO_DATA.

    Regression for the observed CoinGecko flow: empty data was retried three
    times and surfaced as 404. It must be a single attempt with a stable code
    and safe context, not a missing-resource response.
    """
    import app.data_providers.base as base_mod
    from app.data_providers.base import ProviderNoDataError
    from app.data_providers.local_fixtures import LocalFixturesProvider

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    calls: list[int] = []

    def no_data(self, symbol, start, end, interval="1D"):
        calls.append(1)
        raise ProviderNoDataError(
            self.id,
            f"no data for {symbol!r}",
            details={"symbol": symbol, "start": start, "end": end},
        )

    monkeypatch.setattr(LocalFixturesProvider, "fetch_ohlcv_raw", no_data)
    c = _client()
    h = _auth(c, "dpnodata@t.com")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "from": "2015-01-01",
            "to": "2015-12-31",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "PROVIDER_NO_DATA"
    assert body["provider"] == "local"
    assert body["symbol"] == "AAPL"
    assert body["start"] == "2015-01-01"
    assert body["end"] == "2015-12-31"
    assert len(calls) == 1, "no-data must never be retried"
    assert c.get("/api/v1/backtests", headers=h).json()["total"] == 0


def test_backtest_with_explicit_synthetic_provider_runs():
    c = _client()
    h = _auth(c, "dps@t.com")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "dataProvider": "synthetic",
            "from": "2022-01-01",
            "to": "2023-12-31",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["provenance"]["provider"] == "synthetic"
    assert d["provenance"]["dataHash"]
    assert d["engine"]["mode"] == "vendor"  # engine is still the vendor


def test_provenance_recorded_in_db_row():
    c = _client()
    h = _auth(c, "dpp@t.com")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    d = c.get(f"/api/v1/backtests/{r.json()['id']}", headers=h).json()
    prov = d["provenance"]
    assert prov["provider"] == d["dataProvider"] == "local"
    assert prov["symbol"] == "AAPL" and prov["interval"] == "1D"
    assert prov["start"] and prov["end"] and prov["rows"] >= 100
    assert len(prov["dataHash"]) == 64
    lst = c.get("/api/v1/backtests", headers=h).json()["items"][0]
    assert lst["dataProvider"] == "local"


def test_no_network_for_offline_providers():
    """local / synthetic / csv_upload must never touch the network."""
    import socket

    real = socket.socket.connect
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(
        OSError("network blocked in test")
    )
    try:
        from app.data_providers.local_fixtures import LocalFixturesProvider
        from app.data_providers.synthetic import SyntheticProvider

        assert len(LocalFixturesProvider().fetch_ohlcv("AAPL", "2022-01-01", "2022-12-31")) > 0
        assert len(SyntheticProvider().fetch_ohlcv("AAPL", "2022-01-01", "2022-06-30")) > 0
    finally:
        socket.socket.connect = real


def test_alphavantage_key_gate(monkeypatch):
    from app.data_providers.alphavantage import AlphaVantageProvider

    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    p = AlphaVantageProvider()
    h = p.health_check()
    assert h["available"] is False and "ALPHAVANTAGE_API_KEY" in h["detail"]
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")
    assert p.health_check()["available"] is False  # placeholder values ignored
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "real-key-123")
    h2 = p.health_check()  # key present; loader import must not 500
    assert isinstance(h2["available"], bool)


# ------------------------------------------------------- registry + env
def test_registry_default_and_enabled(monkeypatch):
    from app.data_providers.registry import (
        default_provider_id,
        enabled_ids,
        get_provider,
        resolve_for_request,
    )

    monkeypatch.setenv("DATA_PROVIDER_DEFAULT", "local")
    assert default_provider_id() == "local"
    assert resolve_for_request(None).id == "local"
    assert resolve_for_request("").id == "local"
    assert resolve_for_request("synthetic").id == "synthetic"
    with pytest.raises(Exception) as ei:
        get_provider("nope")
    assert "unknown data provider" in str(ei.value)
    monkeypatch.setenv("DATA_PROVIDERS_ENABLED", "local,synthetic")
    assert enabled_ids() == ["local", "synthetic"]
    with pytest.raises(Exception) as ei2:
        get_provider("stooq")  # disabled
    assert "not enabled" in str(ei2.value)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.delenv("DATA_PROVIDER_DEFAULT", raising=False)
    assert default_provider_id() == "synthetic"


def test_csv_upload_endpoint_contract():
    c = _client()
    h = _auth(c, "up@t.com")
    r = c.post(
        "/api/v1/data-providers/csv-upload", json={"symbol": "APITEST", "csv": GOOD_CSV}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["rows"] == 17
    bad = c.post(
        "/api/v1/data-providers/csv-upload",
        json={"symbol": "X", "csv": "date,open\n2022-01-03,1"},
        headers=h,
    )
    assert bad.status_code == 422


def test_optional_provider_reports_missing_package(monkeypatch):
    """Phase 12: optional packages degrade to available=false with a clear reason."""
    import app.data_providers.vendor_shim as vendor_shim
    from app.data_providers.yfinance_provider import YFinanceProvider

    monkeypatch.setattr(vendor_shim.importlib.util, "find_spec", lambda name: None)
    assert YFinanceProvider().health_check() == {
        "available": False,
        "detail": "package yfinance not installed",
    }


# ------------------------------------------------------- FX symbol mapping
def test_keyed_fx_providers_map_canonical_pairs():
    """FX eligibility must be real: configured providers need valid FX symbols."""
    from app.data_providers.polygon import PolygonProvider
    from app.data_providers.twelvedata import TwelveDataProvider

    td = TwelveDataProvider()
    poly = PolygonProvider()

    # Canonical FX (six letters, no separator) -> provider-native FX symbol.
    assert td._twelvedata_symbol("EURUSD") == "EUR/USD"
    assert td._twelvedata_symbol("USDJPY") == "USD/JPY"
    assert poly._polygon_symbol("EURUSD") == "C:EURUSD"
    assert poly._polygon_symbol("GBPUSD") == "C:GBPUSD"

    # Existing crypto/equity mappings must be unchanged.
    assert td._twelvedata_symbol("BTC-USDT") == "BTC/USDT"
    assert poly._polygon_symbol("BTC-USD") == "X:BTCUSD"
    assert td._twelvedata_symbol("AAPL.US") == "AAPL"
    assert poly._polygon_symbol("AAPL.US") == "AAPL"


# ------------------------------------------------------- instrument registry
def test_instrument_registry_known_symbols():
    from app.instruments import get_instrument

    aapl = get_instrument("AAPL")
    assert aapl is not None
    assert aapl.asset_class == "equity"
    assert aapl.backtest_eligible is True

    btc = get_instrument("BTC-USD")
    assert btc is not None
    assert btc.asset_class == "crypto"
    assert btc.backtest_eligible is True
    assert btc.base_currency == "BTC"
    assert btc.quote_currency == "USD"

    eth = get_instrument("ETH-USDT")
    assert eth is not None
    assert eth.asset_class == "crypto"
    assert eth.quote_currency == "USDT"

    eur = get_instrument("EURUSD")
    assert eur is not None
    assert eur.asset_class == "fx"
    assert eur.backtest_eligible is False  # no credential-free OHLCV source

    gdp = get_instrument("FRED:GDP")
    assert gdp is not None
    assert gdp.asset_class == "macro_reference"
    assert gdp.backtest_eligible is False  # macro, not tradable

    assert get_instrument("UNKNOWN") is None


def test_instrument_registry_eligible_symbols():
    from app.instruments import backtest_eligible_symbols

    eligible = backtest_eligible_symbols()
    for s in ("AAPL", "MSFT", "NVDA", "TSLA", "AMD", "SPY", "2222.SR", "1120.SR"):
        assert s in eligible, f"{s} should be backtest-eligible"
    for s in ("BTC-USD", "ETH-USD", "BTC-USDT", "ETH-USDT"):
        assert s in eligible, f"{s} should be backtest-eligible"
    assert "EURUSD" not in eligible
    assert "FRED:GDP" not in eligible


def test_instrument_eligible_providers():
    from app.instruments import eligible_providers

    # AAPL at 1D should have yfinance and stooq eligible
    provs = eligible_providers("AAPL", "1D")
    assert "yfinance" in provs
    assert "stooq" in provs

    # BTC-USD at 1D should have binance_public, ccxt, yfinance
    provs = eligible_providers("BTC-USD", "1D")
    assert "binance_public" in provs
    assert "ccxt" in provs
    assert "yfinance" in provs

    # Unknown symbol -> no providers
    assert eligible_providers("UNKNOWN", "1D") == []


# ------------------------------------------------------- adapter validation
def test_adapter_accepts_crypto_asset():
    from app.adapter import _reject_if_banned

    cfg = {
        "asset": "BTC-USD",
        "leverage": 1,
        "short": False,
        "margin": False,
        "templateId": "ma-crossover",
        "params": {},
    }
    _reject_if_banned(cfg)  # should not raise


def test_adapter_rejects_fx_without_ohlcv_source():
    from app.adapter import EngineRejectedError, _reject_if_banned

    cfg = {
        "asset": "EURUSD",
        "leverage": 1,
        "short": False,
        "margin": False,
        "templateId": "ma-crossover",
        "params": {},
    }
    with pytest.raises(EngineRejectedError) as ei:
        _reject_if_banned(cfg)
    assert ei.value.code == "ENGINE_NOT_ALLOWED"
    assert "no genuine OHLCV backtest source" in str(ei.value)


def test_adapter_rejects_unknown_symbol():
    from app.adapter import EngineRejectedError, _reject_if_banned

    cfg = {
        "asset": "NOTAREALSYMBOL",
        "leverage": 1,
        "short": False,
        "margin": False,
        "templateId": "ma-crossover",
        "params": {},
    }
    with pytest.raises(EngineRejectedError) as ei:
        _reject_if_banned(cfg)
    assert ei.value.code == "ENGINE_NOT_ALLOWED"
    assert "not a registered instrument" in str(ei.value)


def test_adapter_still_accepts_equity():
    from app.adapter import _reject_if_banned

    cfg = {
        "asset": "AAPL",
        "leverage": 1,
        "short": False,
        "margin": False,
        "templateId": "ma-crossover",
        "params": {},
    }
    _reject_if_banned(cfg)  # should not raise


# ------------------------------------------------------- fallback
def test_fallback_disabled_raises_original_error(monkeypatch, tmp_path):
    import app.data_providers.base as base_mod
    import app.data_providers.registry as reg
    from app.data_providers.base import ProviderError
    from app.data_providers.local_fixtures import LocalFixturesProvider

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("DATA_PROVIDER_FALLBACK", "0")
    monkeypatch.setattr(
        reg,
        "FALLBACK_ENABLED",
        os.environ.get("DATA_PROVIDER_FALLBACK", "1") not in ("0", "false", "False", "no"),
    )
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.0)

    def down(self, symbol, start, end, interval="1D"):
        raise ProviderError(self.id, "UPSTREAM_UNAVAILABLE", "simulated outage")

    monkeypatch.setattr(LocalFixturesProvider, "fetch_ohlcv_raw", down)

    with __import__("pytest").raises(ProviderError) as ei:
        reg.fetch_bars(None, "AAPL", "2022-01-01", "2022-12-31", "1D")
    assert ei.value.provider == "local"
    assert ei.value.code == "UPSTREAM_UNAVAILABLE"


def test_fallback_provenance_records_primary(monkeypatch):
    """When fallback occurs, provenance names the alternative provider and
    records the primary provider + reason. (Uses mock providers to avoid
    network; tests the fallback decision logic, not live connectivity.)"""
    from app.data_providers.registry import _providers_compatible

    # local -> synthetic are NOT compatible (non-market datasets never mix)
    assert _providers_compatible("local", "synthetic", "AAPL", "1D") is False

    # yfinance (adjusted) -> stooq (unadjusted) is NOT compatible: falling
    # back would silently change the price-adjustment semantics of an equity.
    assert _providers_compatible("yfinance", "stooq", "AAPL", "1D") is False
    assert _providers_compatible("stooq", "yfinance", "AAPL", "1D") is False

    # Same adjustment semantics + same instrument ARE compatible.
    assert _providers_compatible("alphavantage", "stooq", "AAPL", "1D") is True

    # equity -> crypto NOT compatible
    assert _providers_compatible("yfinance", "ccxt", "AAPL", "1D") is False

    # BTC-USD is priced in USD; BTC-USDT carries a different quote currency and
    # must never substitute for it (and vice versa). Non-crypto providers cannot serve crypto.
    assert _providers_compatible("ccxt", "coingecko", "BTC-USD", "1D") is False
    assert _providers_compatible("binance_public", "stooq", "BTC-USDT", "1D") is False

    # TwelveData and Binance Public are both crypto spot providers for BTC-USDT.
    assert _providers_compatible("binance_public", "twelvedata", "BTC-USDT", "1D") is True

    # Same instrument, same raw-price semantics: compatible.
    assert _providers_compatible("binance_public", "ccxt", "BTC-USDT", "1D") is True

    # Interval must match; ccxt has no monthly bars.
    assert _providers_compatible("binance_public", "ccxt", "BTC-USDT", "1M") is False

    # FX providers are NOT interchangeable: bid/mid price basis and volume
    # semantics differ, so a fallback would silently change the dataset.
    assert _providers_compatible("twelvedata", "polygon", "EURUSD", "1D") is False


# ------------------------------------------------------- missing credentials
def test_keyed_provider_missing_key_not_configured(monkeypatch):
    from app.data_providers.base import ERR_NOT_CONFIGURED, ProviderError
    from app.data_providers.fred import FredProvider

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    p = FredProvider()
    h = p.health_check()
    assert h["available"] is False
    assert "FRED_API_KEY" in h["detail"]

    with __import__("pytest").raises(ProviderError) as ei:
        p.fetch_ohlcv("GDP", "2022-01-01", "2022-12-31", "1D")
    assert ei.value.code == ERR_NOT_CONFIGURED
    assert "FRED_API_KEY" in str(ei.value)
    assert ei.value.provider == "fred"
