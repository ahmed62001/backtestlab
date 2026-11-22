"""Phase 5 — public market API security regression tests.

The public endpoint is internet-exposed before authentication. These tests
exercise allowlisting, input hardening, method restrictions, rate limiting,
cache isolation, single-flight, and data exposure.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

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
def client(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "0")
    app = create_app()
    market._public_cache.clear()
    market._public_rate.clear()
    market._public_key_locks.clear()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        market._public_cache.clear()
        market._public_rate.clear()
        market._public_key_locks.clear()


def _frame(periods=3, start="2026-11-10"):
    import pandas as pd

    idx = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(periods)],
            "high": [102.0 + i for i in range(periods)],
            "low": [99.0 + i for i in range(periods)],
            "close": [101.0 + i for i in range(periods)],
            "volume": [1000.0] * periods,
        },
        index=idx,
    )


def _result():
    return BarsResult(
        frame=_frame(),
        provenance={"provider": "yfinance", "cache": "miss", "cache_age_s": 0},
    )


class _FakeProv:
    id = "yfinance"
    intervals = ("1D", "1H", "1W", "1M")


@pytest.fixture()
def fake_provider(monkeypatch):
    calls = {"n": 0}

    def _fetch(*a, **k):
        calls["n"] += 1
        time.sleep(0.05)
        return _FakeProv(), _result()

    monkeypatch.setattr(market, "fetch_bars", _fetch)
    return calls


# ---------------------------------------------------------------- methods
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_public_routes_are_read_only(client, method):
    r = getattr(client, method)("/api/v1/public/market/series?symbol=GC%3DF")
    assert r.status_code in (404, 405), r.status_code
    assert r.status_code != 500
    r2 = getattr(client, method)("/api/v1/public/market/instruments")
    assert r2.status_code in (404, 405)
    assert r2.status_code != 500


# ---------------------------------------------------------------- symbols
@pytest.mark.parametrize(
    "raw",
    [
        "aapl",
        "AAPL ",
        " AAPL",
        "ＡＡＰＬ",  # full-width
        "AAPL\r\nX-Injected: 1",
        "AAPL%00",
        "../../etc/passwd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "%252e%252e%252f",
        "A" * 4096,
        "\x00",
        "'; DROP TABLE users; --",
        "<script>alert(1)</script>",
    ],
)
def test_symbol_input_never_crashes_or_escapes_allowlist(client, fake_provider, raw):
    r = client.get("/api/v1/public/market/series", params={"symbol": raw, "interval": "1D"})
    assert r.status_code in (200, 400, 404), (raw[:20], r.status_code)
    assert r.status_code != 500
    body = r.text
    # No reflected script payload, no stack trace, no filesystem paths.
    assert "<script>" not in body
    assert "Traceback" not in body
    assert "/home/" not in body
    if r.status_code == 400:
        assert r.json()["code"] == "BAD_SYMBOL"
    if len(raw) > 32:
        assert r.status_code == 400


def test_duplicated_query_parameters_are_safe(client, fake_provider):
    r = client.get("/api/v1/public/market/series?symbol=AAPL&symbol=GC%3DF&interval=1D&interval=1H")
    assert r.status_code in (200, 400, 404)
    assert r.status_code != 500


def test_unknown_symbol_is_404_and_does_not_reveal_registry(client):
    r = client.get("/api/v1/public/market/series", params={"symbol": "NOPE123", "interval": "1D"})
    assert r.status_code == 404
    assert "not available" in r.json()["message"]


def test_bad_interval_and_limit_are_rejected(client, fake_provider):
    assert client.get("/api/v1/public/market/series?symbol=AAPL&interval=5m").status_code == 400
    assert client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D&limit=0").status_code == 400
    assert (
        client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D&limit=999999").status_code
        == 400
    )


# ---------------------------------------------------------------- rate limit
def test_rate_limit_is_enforced_and_has_retry_after(client, monkeypatch, fake_provider):
    monkeypatch.setattr(market, "_PUBLIC_RATE_MAX", 3)
    statuses = [
        client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D").status_code
        for _ in range(5)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code == 429
    assert r.headers.get("retry-after")


def test_spoofed_forwarded_headers_do_not_bypass_limit(client, monkeypatch, fake_provider):
    monkeypatch.setattr(market, "_PUBLIC_RATE_MAX", 2)
    codes = []
    for i in range(4):
        r = client.get(
            "/api/v1/public/market/series?symbol=AAPL&interval=1D",
            headers={"X-Forwarded-For": f"10.0.0.{i}", "X-Real-IP": f"10.0.0.{i}"},
        )
        codes.append(r.status_code)
    assert 429 in codes  # untrusted headers must not create new limiter keys


def test_trusted_proxy_headers_separate_clients(client, monkeypatch, fake_provider):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    monkeypatch.setattr(market, "_PUBLIC_RATE_MAX", 1)
    a = client.get(
        "/api/v1/public/market/series?symbol=AAPL&interval=1D",
        headers={"X-Real-IP": "203.0.113.10"},
    )
    b = client.get(
        "/api/v1/public/market/series?symbol=AAPL&interval=1D",
        headers={"X-Real-IP": "203.0.113.11"},
    )
    assert a.status_code == 200
    assert b.status_code == 200


# ---------------------------------------------------------------- caching
def test_cache_is_isolated_per_symbol_and_interval(client, fake_provider):
    a = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    b = client.get("/api/v1/public/market/series?symbol=BTC-USD&interval=1D")
    c = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1W")
    assert a.status_code == b.status_code == c.status_code == 200
    # AAPL and BTC-USD must be distinct cache entries; a symbol cannot be served
    # another symbol's payload.
    assert a.json()["symbol"] == "AAPL"
    assert b.json()["symbol"] == "BTC-USD"
    assert c.json()["interval"] == "1W"
    assert len(market._public_cache) == 3


def test_identical_concurrent_requests_are_single_flight(client, fake_provider):
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(
                client.get, "/api/v1/public/market/series?symbol=AAPL&interval=1D"
            )
            for _ in range(8)
        ]
        responses = [f.result() for f in futures]
    assert all(r.status_code == 200 for r in responses)
    assert fake_provider["n"] == 1  # exactly one upstream call


def test_provider_failure_does_not_poison_the_cache(client, monkeypatch):
    def _boom(*a, **k):
        raise ProviderError("yfinance", "UPSTREAM_UNAVAILABLE", "provider down")

    monkeypatch.setattr(market, "fetch_bars", _boom)
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code in (502, 503, 504)
    assert r.json()["retryable"] is True
    assert market._public_cache == {}

    # A later success must be served normally (no negative cache).
    monkeypatch.setattr(market, "fetch_bars", lambda *a, **k: (_FakeProv(), _result()))
    r2 = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r2.status_code == 200


def test_stale_fallback_is_labelled_and_bounded(client, monkeypatch):
    monkeypatch.setattr(market, "fetch_bars", lambda *a, **k: (_FakeProv(), _result()))
    first = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert first.status_code == 200

    def _boom(*a, **k):
        raise ProviderError("yfinance", "UPSTREAM_UNAVAILABLE", "provider down")

    monkeypatch.setattr(market, "fetch_bars", _boom)
    # Age the cache beyond its TTL but inside the stale allowance.
    key = ("AAPL", "1D")
    stamp, payload = market._public_cache[key]
    market._public_cache[key] = (stamp - market._PUBLIC_TTL_S["1D"] - 1, payload)
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code == 200
    assert r.json()["dataStatus"] == "stale"
    assert r.json()["staleSince"]


# ---------------------------------------------------------------- exposure
def test_public_response_has_no_cookies_or_secrets(client, fake_provider):
    r = client.get("/api/v1/public/market/series?symbol=AAPL&interval=1D")
    assert r.status_code == 200
    assert "set-cookie" not in {k.lower() for k in r.headers.keys()}
    assert r.headers.get("cache-control", "").startswith("public")
    text = r.text.lower()
    for needle in ("api_key", "apikey", "authorization", "bearer ", "cachedir", "/home/"):
        assert needle not in text


def test_public_endpoints_expose_no_account_data(client):
    inst = client.get("/api/v1/public/market/instruments")
    assert inst.status_code == 200
    body = inst.json()
    assert set(body.keys()) == {"items", "defaultSymbol", "provider"}
    for item in body["items"]:
        assert set(item.keys()) == {"symbol", "displayName", "assetClass", "currency", "intervals"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/market/universe",
        "/api/v1/market/quotes?symbols=AAPL",
        "/api/v1/market/series?symbol=AAPL",
        "/api/v1/backtests",
        "/api/v1/usage",
        "/api/v1/auth/me",
        "/api/v1/invoices",
        "/api/v1/notifications",
    ],
)
def test_protected_endpoints_reject_anonymous(client, path):
    r = client.get(path)
    assert r.status_code in (401, 403), (path, r.status_code)


def test_templates_is_intentionally_public_and_account_free(client):
    """The strategy template catalog is static product metadata, not user data."""
    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    assert isinstance(items, list)
    for item in items:
        assert set(item.keys()) >= {"id", "defaultParams"} or "id" in item
        for forbidden in ("userId", "user_id", "email", "token"):
            assert forbidden not in item


def test_users_cannot_read_or_delete_other_users_runs(client):
    import uuid

    suffix = uuid.uuid4().hex[:8]
    a = client.post(
        "/api/v1/auth/register",
        json={"name": "Iso A", "email": f"iso-a-{suffix}@example.test", "password": "password123"},
    ).json()
    b = client.post(
        "/api/v1/auth/register",
        json={"name": "Iso B", "email": f"iso-b-{suffix}@example.test", "password": "password123"},
    ).json()
    ha = {"Authorization": "Bearer " + a["token"]}
    hb = {"Authorization": "Bearer " + b["token"]}
    run = client.post(
        "/api/v1/backtests",
        json={"templateId": "rsi", "asset": "SPY", "initialCapital": 10000},
        headers=ha,
    )
    assert run.status_code == 201, run.text
    rid = run.json()["id"]
    assert client.get(f"/api/v1/backtests/{rid}", headers=hb).status_code == 404
    assert client.delete(f"/api/v1/backtests/{rid}", headers=hb).status_code == 404
    # The owner still sees it afterwards.
    assert client.get(f"/api/v1/backtests/{rid}", headers=ha).status_code == 200

