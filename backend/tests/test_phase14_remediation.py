"""Phase 14 remediation regressions — one block per audited defect ID.

Each test reproduces the *original failure mode* from
``docs/PRE_PHASE_15_AUDIT_PROGRESS.md`` and asserts the corrected behaviour.
These tests are additive to the audit evidence; they do not replace it.
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
import uuid
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

BASE = pathlib.Path(__file__).resolve().parent.parent
DAY = "2024-02-01"


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
_CLIENT = None


def client():
    global _CLIENT
    if _CLIENT is None:
        from app.main import create_app
        from fastapi.testclient import TestClient

        _CLIENT = TestClient(create_app(), raise_server_exceptions=False)
    return _CLIENT


def new_email(tag: str) -> str:
    return f"p14-{tag}-{uuid.uuid4().hex[:8]}@example.com"


def auth(c, tag="user"):
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Phase14", "email": new_email(tag), "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()


def unique_symbol(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


def bars_frame(start: str, end: str, close: float = 100.0, periods: int | None = None):
    if periods is None:
        idx = pd.date_range(start, end, freq="D", tz="UTC")
    else:
        idx = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    n = len(idx)
    return pd.DataFrame(
        {
            "open": [close] * n,
            "high": [close + 1] * n,
            "low": [close - 1] * n,
            "close": [close] * n,
            "volume": [1000.0] * n,
        },
        index=idx,
    )


class FakeProvider:
    id = "fake"
    adjusted = False

    def __init__(self, factory, sleep: float = 0.0):
        self.factory = factory
        self.sleep = sleep
        self.calls = 0
        self.lock = threading.Lock()

    def fetch_ohlcv(self, symbol, start, end, interval="1D"):
        with self.lock:
            self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        return self.factory(start, end)


def svc():
    from app.data_store.service import MarketDataService

    return MarketDataService()


def use_provider(monkeypatch, fake):
    import app.data_store.service as service_mod

    monkeypatch.setattr(service_mod, "get_provider", lambda _pid: fake)


# --------------------------------------------------------------------------
# Phase 1 — frontend/session defects
# --------------------------------------------------------------------------
def test_d_ph1_03_change_password_endpoint_is_real():
    c = client()
    h, _ = auth(c, "pw")
    r = c.post(
        "/api/v1/auth/password",
        json={"currentPassword": "wrong-password", "newPassword": "newpassword123"},
        headers=h,
    )
    assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    r = c.post(
        "/api/v1/auth/password",
        json={"currentPassword": "password123", "newPassword": "newpassword123"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["ok"] is True


def test_d_ph1_04_reset_tokens_are_single_use_and_change_the_hash():
    from app.auth import issue_password_reset
    from app.db import SessionLocal, User
    from sqlalchemy import select

    c = client()
    email = new_email("reset")
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Reset User", "email": email, "password": "password123"},
    )
    assert r.status_code == 201
    with SessionLocal() as s:
        uid = s.scalar(select(User.id).where(User.email == email))

    token = issue_password_reset(uid)
    r = c.post("/api/v1/auth/reset", json={"token": token, "password": "brandnew123"})
    assert r.status_code == 200, r.text
    # Replaying the same token must fail.
    r = c.post("/api/v1/auth/reset", json={"token": token, "password": "another123"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_TOKEN"
    # Old password no longer works, new one does.
    assert (
        c.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).status_code
        == 401
    )
    assert (
        c.post("/api/v1/auth/login", json={"email": email, "password": "brandnew123"}).status_code
        == 200
    )


# --------------------------------------------------------------------------
# Phase 2 — data providers
# --------------------------------------------------------------------------
def test_d_ph2_01_requests_is_a_declared_dependency():
    req = (BASE / "requirements.txt").read_text().lower()
    assert "requests==" in req


def test_d_ph2_02_keyed_provider_without_key_is_not_configured(monkeypatch):
    from app.data_providers.base import ProviderError
    from app.data_providers.registry import get_provider

    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    p = get_provider("alphavantage")
    with pytest.raises(ProviderError) as exc:
        p.fetch_ohlcv_raw("AAPL", "2022-01-01", "2022-02-01", "1D")
    assert exc.value.code == "PROVIDER_NOT_CONFIGURED"


def test_d_ph2_03_network_errors_classify_as_unavailable():
    import httpx
    from app.data_providers.base import classify_error

    for exc in (httpx.ConnectError("dns"), httpx.ReadError("reset"), httpx.ConnectTimeout("t")):
        e = classify_error("stooq", exc)
        assert e.code == "UPSTREAM_UNAVAILABLE", type(exc).__name__


def test_d_ph2_04_health_detail_names_the_env_var(monkeypatch):
    from app.data_providers.registry import get_provider

    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    for pid, env in (("tiingo", "TIINGO_API_KEY"), ("alphavantage", "ALPHAVANTAGE_API_KEY")):
        detail = get_provider(pid).health_check()["detail"]
        assert env in detail and "not configured" in detail


def test_d_ph2_05_local_store_timeframes_match_intervals():
    from app.data_providers.registry import get_provider

    p = get_provider("local_store")
    assert set(p.capabilities.timeframes) == set(p.intervals)


def test_d_ph2_06_not_configured_is_not_retried(monkeypatch):
    from app.data_providers.base import ProviderError, with_retries

    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise ProviderError("x", "PROVIDER_NOT_CONFIGURED", "missing key")

    with pytest.raises(ProviderError):
        with_retries(boom, "x")
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# Phase 3 — market data integrity
# --------------------------------------------------------------------------
def test_d_ph3_01_non_finite_prices_are_dropped():
    from app.data_store.normalize import normalize_bars

    raw = bars_frame("2024-01-01", "2024-01-03")
    raw.loc[raw.index[1], "high"] = np.inf
    res = normalize_bars(raw, "INF", "fake", "1d")
    assert len(res.frame) == 2
    assert res.rows_invalid == 1
    assert any(w["code"] == "DROPPED_NON_FINITE_PRICE" for w in res.warnings)


def test_d_ph3_02_invalid_volume_is_coerced_and_reported():
    from app.data_store.normalize import normalize_bars

    raw = bars_frame("2024-01-01", "2024-01-03")
    raw.loc[raw.index[0], "volume"] = np.nan
    raw.loc[raw.index[1], "volume"] = -50.0
    res = normalize_bars(raw, "VOL", "fake", "1d")
    assert len(res.frame) == 3
    assert list(res.frame["volume"]) == [0.0, 0.0, 1000.0]
    assert any(w["code"] == "COERCED_INVALID_VOLUME" for w in res.warnings)


def test_d_ph3_03_missing_timestamp_column_is_rejected_not_fabricated():
    from app.data_store.normalize import normalize_bars

    raw = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]}
    )
    res = normalize_bars(raw, "NODATE", "fake", "1d")
    assert res.frame.empty
    assert res.rows_invalid == 1
    assert any(w["code"] == "BAD_INPUT" and "fabricate" in w["message"] for w in res.warnings)


def test_d_ph3_04_gap_detection_uses_the_timeframe_step():
    from app.data_store.normalize import normalize_bars

    weekly = pd.DataFrame(
        {
            "open": [100.0] * 9,
            "high": [101.0] * 9,
            "low": [99.0] * 9,
            "close": [100.0] * 9,
            "volume": [1000.0] * 9,
        },
        index=pd.date_range("2024-01-01", periods=9, freq="7D", tz="UTC"),
    )
    wres = normalize_bars(weekly, "W", "fake", "1w")
    assert not any(w["code"] == "LARGE_GAP" for w in wres.warnings)

    minute = bars_frame("2024-01-01", "2024-01-01", periods=3)
    minute.index = pd.to_datetime(
        ["2024-01-01T00:00:00Z", "2024-01-01T00:01:00Z", "2024-01-01T00:20:00Z"]
    )
    mres = normalize_bars(minute, "M", "fake", "1m")
    assert any(w["code"] == "LARGE_GAP" for w in mres.warnings)


def test_d_ph3_05_nan_volume_hashes_like_zero():
    from app.data_store.service import _canonical_hash

    base = {"ts": "2024-01-01T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5}
    assert _canonical_hash([{**base, "volume": float("nan")}]) == _canonical_hash(
        [{**base, "volume": 0.0}]
    )


def test_d_ph3_06_cold_fetch_is_reported_live(monkeypatch):
    fake = FakeProvider(lambda s, e: bars_frame(s, e))
    use_provider(monkeypatch, fake)
    df, prov = svc().get_bars("fake", unique_symbol("COLD"), "1d", "2024-03-01", "2024-03-11")
    # The fixture provider returns an inclusive end bar (11 rows), which the
    # store keeps and includes in coverage.
    assert len(df) == 11
    assert prov["retrieval"] == "live"


def test_d_ph3_07_refresh_refetches_the_full_range(monkeypatch):
    fake = FakeProvider(lambda s, e: bars_frame(s, e))
    use_provider(monkeypatch, fake)
    symbol = unique_symbol("REF")
    svc().get_bars("fake", symbol, "1d", "2024-03-01", "2024-03-11")
    assert fake.calls == 1
    df, _ = svc().get_bars("fake", symbol, "1d", "2024-03-01", "2024-03-11", refresh=True)
    assert fake.calls == 2 and len(df) == 11


def test_d_ph3_08_failed_coverage_is_not_treated_as_covered(monkeypatch):
    from app.data_store.repository import ensure_instrument, get_coverage, upsert_coverage

    symbol = unique_symbol("FAIL")
    fake = FakeProvider(lambda s, e: bars_frame(s, e))
    use_provider(monkeypatch, fake)
    inst = ensure_instrument(symbol, "equity")
    upsert_coverage(
        inst, "fake", "1d", "2024-04-01", "2024-04-11", 0, "", status="failed", expires_at=None
    )
    svc().get_bars("fake", symbol, "1d", "2024-04-01", "2024-04-11")
    assert fake.calls == 1
    cov = get_coverage(inst, "fake", "1d", False)
    assert any(c["status"] == "complete" for c in cov), cov
    # The newly complete row must satisfy a second request without a refetch.
    svc().get_bars("fake", symbol, "1d", "2024-04-01", "2024-04-11")
    assert fake.calls == 1


def test_d_ph3_09_store_only_read_is_not_labelled_live(monkeypatch):
    from app.data_store.repository import ensure_instrument, upsert_bars, upsert_coverage

    symbol = unique_symbol("STORE")
    fake = FakeProvider(lambda s, e: bars_frame(s, e))
    use_provider(monkeypatch, fake)
    inst = ensure_instrument(symbol, "equity")
    frame = bars_frame("2024-05-01", "2024-05-11")
    bars = [
        {
            "ts": ts.isoformat(),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }
        for ts, r in frame.iterrows()
    ]
    upsert_bars(inst, "fake", "1d", bars, False)
    upsert_coverage(
        inst, "fake", "1d", "2024-05-01", "2024-05-06", len(bars), "x", status="complete"
    )
    upsert_coverage(
        inst, "fake", "1d", "2024-05-06", "2024-05-11", len(bars), "x", status="complete"
    )
    _, prov = svc().get_bars("fake", symbol, "1d", "2024-05-01", "2024-05-11")
    assert fake.calls == 0
    assert prov["retrieval"] == "store"


def test_d_ph3_10_boundaries_compare_as_instants(monkeypatch):
    fake = FakeProvider(lambda s, e: bars_frame(s, e))
    use_provider(monkeypatch, fake)
    symbol = unique_symbol("INST")
    svc().get_bars("fake", symbol, "1d", "2024-06-01", "2024-06-11")
    assert fake.calls == 1
    df, prov = svc().get_bars(
        "fake", symbol, "1d", "2024-06-01T00:00:00+00:00", "2024-06-11T00:00:00+00:00"
    )
    # The cache read is half-open [start, end), so it returns 10 of the 11
    # stored bars; the equivalence assertion is the absence of a refetch.
    assert fake.calls == 1 and len(df) == 10 and prov["retrieval"] == "store"


def test_d_ph3_11_identical_requests_are_coalesced(monkeypatch):
    fake = FakeProvider(lambda s, e: bars_frame(s, e), sleep=0.15)
    use_provider(monkeypatch, fake)
    symbol = unique_symbol("COAL")
    errors: list[BaseException] = []

    def run():
        try:
            svc().get_bars("fake", symbol, "1d", "2024-07-01", "2024-07-11")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert fake.calls == 1


def test_d_ph3_12_concurrent_coverage_upserts_keep_one_row():
    from app.data_store.repository import ensure_instrument, upsert_coverage
    from app.db import MarketCoverage, SessionLocal
    from sqlalchemy import func, select

    symbol = unique_symbol("COV")
    inst = ensure_instrument(symbol, "equity")
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def run():
        try:
            barrier.wait()
            upsert_coverage(
                inst, "fake", "1d", "2024-08-01", "2024-08-11", 10, "h", status="complete"
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    with SessionLocal() as s:
        n = s.scalar(
            select(func.count())
            .select_from(MarketCoverage)
            .where(
                MarketCoverage.instrument_id == inst,
                MarketCoverage.provider == "fake",
                MarketCoverage.range_start == "2024-08-01T00:00:00+00:00",
                MarketCoverage.range_end == "2024-08-11T00:00:00+00:00",
            )
        )
    assert n == 1


def test_d_ph3_13_partial_invalid_subrange_never_marks_complete(monkeypatch):
    from app.data_store.repository import ensure_instrument, get_coverage

    def factory(start, end):
        frame = bars_frame(start, end, periods=9)
        frame.iloc[:8, frame.columns.get_loc("close")] = np.nan
        return frame

    symbol = unique_symbol("PART")
    fake = FakeProvider(factory)
    use_provider(monkeypatch, fake)
    svc().get_bars("fake", symbol, "1d", "2024-09-01", "2024-09-11")
    inst = ensure_instrument(symbol, "equity")
    cov = get_coverage(inst, "fake", "1d", False)
    assert cov and all(c["status"] != "complete" for c in cov), cov


def test_d_ph3_14_storage_failure_is_infrastructure(monkeypatch):
    import app.data_store.service as service_mod
    from app.data_providers.base import ProviderError, http_status_for_code

    def boom(*_a, **_k):
        raise RuntimeError("attempt to write a readonly database")

    monkeypatch.setattr(service_mod, "ensure_instrument", boom)
    with pytest.raises(ProviderError) as exc:
        svc().get_bars("fake", unique_symbol("RO"), "1d", "2024-10-01", "2024-10-11")
    assert exc.value.code == "DATA_STORE_UNAVAILABLE"
    assert http_status_for_code("DATA_STORE_UNAVAILABLE") == 503


def test_d_ph3_15_cli_ingest_hash_verifies(tmp_path):
    from app.cli import cmd_ingest_file
    from app.data_store.repository import ensure_instrument, verify_coverage_hashes

    symbol = unique_symbol("CLI")
    frame = bars_frame("2024-01-01", "2024-01-21")
    path = tmp_path / "bars.csv"
    frame.rename_axis("date").to_csv(path)
    args = SimpleNamespace(
        file=str(path), provider="fake", symbol=symbol, interval="1D", asset_class="equity"
    )
    cmd_ingest_file(args)
    inst = ensure_instrument(symbol, "equity")
    rows = [r for r in verify_coverage_hashes() if r["instrumentId"] == inst]
    assert rows and all(r["ok"] for r in rows), rows


def test_d_ph3_16_csv_upload_rejects_invalid_ohlc():
    from app.data_providers.base import ProviderError
    from app.data_providers.csv_upload import validate_upload_csv

    bad = "date,open,high,low,close,volume\n2024-01-01,10,5,1,10,100\n"
    with pytest.raises(ProviderError) as exc:
        validate_upload_csv(bad.encode(), "BAD")
    assert exc.value.code == "BAD_INPUT"


def test_d_ph3_17_ingest_file_validates_and_dedupes(tmp_path):
    from app.cli import cmd_ingest_file
    from app.data_store.repository import ensure_instrument, read_bars, verify_coverage_hashes

    symbol = unique_symbol("DUP")
    path = tmp_path / "dupe.csv"
    path.write_text(
        "date,open,high,low,close,volume\n2024-01-01,10,11,9,10,100\n2024-01-01,10,11,9,10,100\n"
    )
    args = SimpleNamespace(
        file=str(path), provider="fake", symbol=symbol, interval="1D", asset_class="equity"
    )
    cmd_ingest_file(args)
    inst = ensure_instrument(symbol, "equity")
    assert len(read_bars(inst, "fake", "1d", "2024-01-01", "2024-01-03", False)) == 1
    rows = [r for r in verify_coverage_hashes() if r["instrumentId"] == inst]
    assert rows and rows[0]["ok"] and rows[0]["rows"] == 1

    bad = tmp_path / "bad.csv"
    bad.write_text("date,open,high,low,close,volume\n2024-01-01,10,5,9,10,100\n")
    with pytest.raises(SystemExit):
        cmd_ingest_file(
            SimpleNamespace(
                file=str(bad), provider="fake", symbol=symbol, interval="1D", asset_class="equity"
            )
        )


# --------------------------------------------------------------------------
# Phase 4 — API & auth
# --------------------------------------------------------------------------
def test_d_ph4_01_refresh_tokens_never_authenticate_api_calls():
    c = client()
    h, body = auth(c, "jwt")
    refresh = body["refresh_token"]
    assert (
        c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
    )

    r = c.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    rotated = r.json()["refresh_token"]
    # Replay of the now-rotated token is rejected.
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    # Revoking the current refresh token makes it unusable.
    assert (
        c.post("/api/v1/auth/revoke", json={"refresh_token": rotated}, headers=h).status_code == 200
    )
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": rotated}).status_code == 401


def test_d_ph4_02_non_finite_backtest_inputs_are_422_without_side_effects():
    c = client()
    h, _ = auth(c, "finite")
    before = len(c.get("/api/v1/backtests", headers=h).json()["items"])
    base = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "from": "2022-01-01",
        "to": "2022-12-31",
        "params": {"fastPeriod": 10, "slowPeriod": 30},
    }
    for field in ("initialCapital", "feePct"):
        # httpx refuses to emit NaN in strict JSON, so send the raw body the
        # original audit used; Python's JSON parser accepts the NaN literal.
        payload = json.dumps({**base, field: float("nan")}, allow_nan=True)
        r = c.post(
            "/api/v1/backtests",
            content=payload.encode(),
            headers={**h, "Content-Type": "application/json"},
        )
        assert r.status_code == 422, (field, r.status_code, r.text)
        assert r.json()["code"] == "BAD_INPUT"
    r = c.get("/api/v1/backtests", headers=h)
    assert r.status_code == 200 and len(r.json()["items"]) == before


def _middleware_scope(path="/api/v1/backtests", headers=None):
    return {"type": "http", "method": "POST", "path": path, "headers": headers or []}


def _run_middleware(scope, chunks):
    import asyncio

    from app.main import BodySizeLimitMiddleware

    sent: list[dict] = []
    it = iter(chunks)

    async def receive():
        try:
            chunk = next(it)
        except StopIteration:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    async def app(_scope, _receive, _send):
        await _send({"type": "http.response.start", "status": 200, "headers": []})
        await _send({"type": "http.response.body", "body": b"ok"})

    asyncio.run(BodySizeLimitMiddleware(app)(scope, receive, send))
    return sent[0]["status"]


def test_d_ph4_03_body_limit_counts_actual_bytes_and_rejects_bad_content_length():
    assert _run_middleware(_middleware_scope(), [b"x" * 100, b"y" * 1_000_001]) == 413
    assert _run_middleware(_middleware_scope(headers=[(b"content-length", b"abc")]), [b"x"]) == 400


def test_d_ph4_04_csv_uploads_are_namespaced_per_tenant():
    c = client()
    ha, _ = auth(c, "tenant-a")
    hb, _ = auth(c, "tenant-b")

    def csv(price: float) -> str:
        lines = ["date,open,high,low,close,volume"]
        for ts in pd.date_range("2022-01-03", periods=250, freq="B"):
            lines.append(f"{ts.date()},{price},{price + 1},{price - 1},{price},1000")
        return "\n".join(lines) + "\n"

    a_upload = c.post(
        "/api/v1/data-providers/csv-upload",
        json={"symbol": "AAPL", "csv": csv(10.0)},
        headers=ha,
    )
    assert a_upload.status_code == 200, a_upload.text
    b_upload = c.post(
        "/api/v1/data-providers/csv-upload",
        json={"symbol": "AAPL", "csv": csv(20.0)},
        headers=hb,
    )
    assert b_upload.status_code == 200, b_upload.text

    def buy_hold(h):
        r = c.post(
            "/api/v1/backtests",
            json={
                "templateId": "buy-hold",
                "asset": "AAPL",
                "from": "2022-01-03",
                "to": "2022-12-30",
                "initialCapital": 10000,
                "feePct": 0,
                "dataProvider": "csv_upload",
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        return r.json()

    a = buy_hold(ha)
    b = buy_hold(hb)
    # A's trade must still be struck at A's price (10), not B's overwrite (20).
    assert a["tradesList"] and a["tradesList"][0]["qty"] > 800
    assert b["tradesList"] and b["tradesList"][0]["qty"] < 600
    assert a["provenance"]["dataHash"] != b["provenance"]["dataHash"]


def test_d_ph4_05_error_envelopes_are_uniform():
    c = client()
    h, _ = auth(c, "env")
    checks = [
        c.get("/api/v1/does-not-exist"),
        c.put("/api/v1/auth/me", headers=h),
        c.post("/api/v1/auth/login", content=b"{", headers={"Content-Type": "application/json"}),
        c.get("/api/v1/backtests?limit=abc", headers=h),
        c.post("/api/v1/auth/register", content=b"", headers={"Content-Type": "application/json"}),
    ]
    for r in checks:
        body = r.json()
        assert {"code", "message", "details", "requestId"} == set(body), (r.status_code, body)
        assert body["requestId"] and body["requestId"] != "-", (r.status_code, body)


def test_d_ph4_06_billing_stubs_are_501_envelopes():
    c = client()
    h, _ = auth(c, "bill")
    for path in ("/api/v1/billing/checkout", "/api/v1/billing/portal"):
        r = c.post(path, json={}, headers=h)
        assert r.status_code == 501, (path, r.status_code, r.text)
        assert r.json()["code"] == "BILLING_NOT_CONFIGURED"
        assert {"code", "message", "details", "requestId"} == set(r.json())
    plans = c.get("/api/v1/plans")
    assert plans.status_code == 200
    body = plans.json()
    assert body["billingEnabled"] is False
    pro = next(p for p in body["items"] if p["id"] == "pro")
    assert pro["available"] is False
    webhook = c.post("/api/v1/billing/webhook", json={})
    assert webhook.status_code == 503
    assert webhook.json()["code"] == "BILLING_NOT_CONFIGURED"
    assert webhook.json()["stored"] is False


def test_d_ph4_07_registration_rejects_unusable_emails():
    c = client()
    for bad in ("@", "foo@", "a@b", " @ "):
        r = c.post(
            "/api/v1/auth/register",
            json={"name": "Bad Email", "email": bad, "password": "password123"},
        )
        assert r.status_code == 422, (bad, r.status_code, r.text)
        assert r.json()["code"] == "INVALID_EMAIL"


def test_d_ph4_08_patch_me_rejects_invalid_values():
    c = client()
    h, _ = auth(c, "patch")
    for payload in (
        {"name": 123},
        {"name": "x"},
        {"language": "fr"},
        {"language": 1},
        {"name": None},
        {"unknown": "x"},
    ):
        r = c.patch("/api/v1/auth/me", json=payload, headers=h)
        assert r.status_code == 422, (payload, r.status_code, r.text)


def test_d_ph4_09_basic_format_dates_are_rejected():
    c = client()
    h, _ = auth(c, "date")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "from": "20220101",
            "to": "20231231",
            "params": {"fastPeriod": 10, "slowPeriod": 30},
        },
        headers=h,
    )
    assert r.status_code == 422 and r.json()["code"] == "BAD_INPUT"


def test_d_ph4_10_json_type_coercion_is_rejected():
    c = client()
    h, _ = auth(c, "coerce")
    base = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "from": "2022-01-01",
        "to": "2022-12-31",
        "params": {"fastPeriod": 10, "slowPeriod": 30},
    }
    for payload in ({**base, "leverage": True}, {**base, "params": None}):
        r = c.post("/api/v1/backtests", json=payload, headers=h)
        assert r.status_code == 422, (payload, r.status_code, r.text)


def test_d_ph4_11_overlong_idempotency_key_is_rejected():
    c = client()
    h, _ = auth(c, "idem")
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "from": "2022-01-01",
            "to": "2022-12-31",
            "params": {"fastPeriod": 10, "slowPeriod": 30},
        },
        headers={**h, "Idempotency-Key": "k" * 129},
    )
    assert r.status_code == 422 and r.json()["code"] == "BAD_INPUT"


def test_d_ph4_12_documented_5mib_csv_is_not_blocked_by_the_global_guard():
    from app.data_providers.csv_upload import MAX_UPLOAD_BYTES

    assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024
    c = client()
    h, _ = auth(c, "bigcsv")
    padding = "x" * 4800
    lines = ["date,open,high,low,close,volume,note"]
    for ts in pd.date_range("2022-01-03", periods=250, freq="B"):
        lines.append(f"{ts.date()},10,11,9,10,1000,{padding}")
    payload = "\n".join(lines) + "\n"
    assert len(payload.encode()) > 1_000_000  # above the old global 1 MB gate
    r = c.post(
        "/api/v1/data-providers/csv-upload",
        json={"symbol": "MSFT", "csv": payload},
        headers=h,
    )
    assert r.status_code == 200, r.text[:300]


# --------------------------------------------------------------------------
# Phase 5 — database integrity
# --------------------------------------------------------------------------
def test_d_ph5_01_concurrent_quota_reservation_never_exceeds_limit():
    from app.db import SessionLocal, Usage
    from app.queue import _reserve_quota
    from sqlalchemy import select

    uid = "u-quota-" + uuid.uuid4().hex[:8]
    day = "2026-11-06"
    limit = 5
    barrier = threading.Barrier(12)
    ok: list[int] = []
    errors: list[BaseException] = []

    def run():
        try:
            barrier.wait()
            with SessionLocal() as s:
                _reserve_quota(s, uid, day, limit)
                s.commit()
            ok.append(1)
        except LookupError:
            pass
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    with SessionLocal() as s:
        used = s.scalar(select(Usage.used).where(Usage.user_id == uid, Usage.day == day))
    assert used == limit and len(ok) == limit


def test_d_ph5_02_concurrent_idempotent_submit_creates_one_job():
    from app.db import Job, SessionLocal, User
    from app.queue import submit_job
    from sqlalchemy import func, select

    uid = "u-idem-" + uuid.uuid4().hex[:8]
    with SessionLocal() as s:
        s.add(User(id=uid, email=f"{uid}@example.com", name="Idem", password_hash="x"))
        s.commit()
    cfg = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "from": "2022-01-01",
        "to": "2022-12-31",
        "params": {"fastPeriod": 10, "slowPeriod": 30},
    }
    key = "same-" + uuid.uuid4().hex[:8]
    barrier = threading.Barrier(4)
    out: list[dict] = []
    errors: list[BaseException] = []

    def run():
        try:
            barrier.wait()
            out.append(submit_job(uid, cfg, key))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len({o["job_id"] for o in out}) == 1, out
    with SessionLocal() as s:
        n = s.scalar(select(func.count()).select_from(Job).where(Job.user_id == uid))
    assert n == 1


def test_d_ph5_03_non_finite_metrics_and_json_are_rejected():
    from app.db import Backtest, SessionLocal

    base = {
        "id": "bt-" + uuid.uuid4().hex[:8],
        "user_id": "u-finite",
        "name": "x",
        "template_id": "ma-crossover",
        "asset": "AAPL",
        "status": "done",
        "created_at": "2026-11-06T00:00:00+00:00",
        "data_provider": "local",
        "data_symbol": "AAPL",
        "data_interval": "1D",
        "data_start": "2022-01-01",
        "data_end": "2022-12-31",
        "data_hash": "",
        "data_rows": 1,
        "config_json": "{}",
    }
    for kwargs in (
        {**base, "result_json": "{}", "sharpe": float("nan")},
        {**base, "result_json": json.dumps({"x": float("inf")})},
    ):
        with SessionLocal() as s:
            with pytest.raises(ValueError):
                s.add(Backtest(**kwargs))
                s.commit()
            s.rollback()


# --------------------------------------------------------------------------
# Phase 6 — financial correctness
# --------------------------------------------------------------------------
def _aapl():
    return pd.read_csv(BASE / "tests" / "fixtures" / "AAPL.csv", index_col=0, parse_dates=True)


def test_d_ph6_01_signals_and_adapter_are_long_only():
    from app.adapter import EngineRejectedError, VibeTradingEngine
    from app.signals import TemplateSignals, signal_series

    df = _aapl()
    for tid, params in (
        ("ma-crossover", {"fastPeriod": 10, "slowPeriod": 30}),
        ("rsi", {"rsiPeriod": 14, "oversold": 30, "overbought": 70}),
        ("mean-reversion", {"lookback": 20, "zEntry": 2, "zExit": 0.5}),
    ):
        sig = signal_series(tid, df, params)
        assert float(sig.min()) >= 0.0 and float(sig.max()) <= 1.0, tid

    # The signal boundary clamps even a deliberately broken template.
    import app.signals as signals_mod

    original = signals_mod.signal_series
    try:
        signals_mod.signal_series = lambda *a, **k: pd.Series(-1.0, index=df.index)
        out = TemplateSignals("ma-crossover", {}).generate({"AAPL": df})
        assert float(out["AAPL"].min()) == 0.0
    finally:
        signals_mod.signal_series = original

    class BadTrade:
        direction = -1

    class BadEngine:
        trades = [BadTrade()]
        equity_snapshots = []

        def __init__(self, *_a, **_k):
            pass

        def run_backtest(self, *_a, **_k):
            return {}, None

    import app.adapter as adapter_mod

    monkey_engine = BadEngine
    original_loader = adapter_mod.load_vendor_engine
    try:
        adapter_mod.load_vendor_engine = lambda: monkey_engine
        with pytest.raises(EngineRejectedError):
            VibeTradingEngine().run(
                {"templateId": "buy-hold", "asset": "AAPL", "from": "2022-01-01"}, df
            )
    finally:
        adapter_mod.load_vendor_engine = original_loader


def test_d_ph6_02_benchmark_curve_tracks_close_not_strategy():
    from app.pipeline import normalize

    class Snap:
        def __init__(self, timestamp, equity):
            self.timestamp = timestamp
            self.equity = equity

    class Eng:
        equity_snapshots = [
            Snap("2022-01-03", 10000.0),
            Snap("2022-01-04", 10100.0),
            Snap("2022-01-05", 10200.0),
        ]
        trades = []

    bars = pd.DataFrame(
        {"close": [100.0, 90.0, 80.0]},
        index=pd.date_range("2022-01-03", periods=3, freq="D", tz="UTC"),
    )
    raw = {
        "total_return": 0.02,
        "max_drawdown": -0.01,
        "sharpe": 0.0,
        "trade_count": 0,
        "benchmark_return": -0.2,
    }
    out = normalize(raw, Eng(), {"initialCapital": 10000, "feePct": 0.1}, bars, {})
    bench = [e["benchmark"] for e in out["equity"]]
    assert bench == [10000.0, 9000.0, 8000.0]
    assert bench != [e["strategy"] for e in out["equity"]]


def test_d_ph6_03_estimated_fees_match_the_commission_formula():
    from app.pipeline import normalize

    class Eng:
        equity_snapshots = []
        trades = []

    out = normalize(
        {"total_return": 0, "max_drawdown": 0, "sharpe": 0, "trade_count": 5},
        Eng(),
        {"initialCapital": 10000, "feePct": 0.1},
        pd.DataFrame(),
        {},
    )
    assert out["costs"]["estimatedFees"] == pytest.approx(50.0)


def test_d_ph6_04_advertised_params_change_the_strategy():
    from app.signals import signal_series

    df = _aapl()
    rsi_a = signal_series("rsi", df, {"rsiPeriod": 14, "oversold": 30, "overbought": 70})
    rsi_b = signal_series("rsi", df, {"rsiPeriod": 14, "oversold": 30, "overbought": 60})
    assert not rsi_a.equals(rsi_b)

    mr_a = signal_series("mean-reversion", df, {"lookback": 20, "zEntry": 2, "zExit": 0.5})
    mr_b = signal_series("mean-reversion", df, {"lookback": 20, "zEntry": 2, "zExit": 1.5})
    assert not mr_a.equals(mr_b)

    dca_a = signal_series("dca", df, {"frequencyDays": 10})
    dca_b = signal_series("dca", df, {"frequencyDays": 60})
    assert not dca_a.equals(dca_b)


def test_d_ph6_05_trades_carry_size_direction_and_trade_return():
    from app.pipeline import normalize

    class Trade:
        exit_time = "2022-02-01"
        exit_price = 110.0
        pnl = 49.0
        direction = 1
        size = 4.95
        pnl_pct = 9.90099

    class Eng:
        equity_snapshots = []
        trades = [Trade()]

    out = normalize(
        {"total_return": 0, "max_drawdown": 0, "sharpe": 0, "trade_count": 1},
        Eng(),
        {"initialCapital": 10000, "feePct": 0.1},
        pd.DataFrame(),
        {},
    )
    t = out["tradesList"][0]
    assert t["qty"] == pytest.approx(4.95)
    assert t["side"] == "sell" and t["direction"] == "long"
    assert t["returnPct"] == pytest.approx(9.901, abs=1e-3)


def test_d_ph6_06_buy_hold_has_no_artificial_warmup():
    from app.signals import signal_series

    df = _aapl()
    sig = signal_series("buy-hold", df, {})
    assert float(sig.iloc[0]) == 1.0 and float(sig.min()) == 1.0


def test_d_ph6_07_monthly_buckets_are_calendar_months():
    from app.synthetic_engine import run_backtest

    out = run_backtest(
        {
            "templateId": "buy-hold",
            "asset": "AAPL",
            "from": "2022-01-01",
            "to": "2023-12-31",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        }
    )
    months = {m["month"] for m in out["monthly"]}
    assert months == set(range(1, 13))


def test_d_ph6_08_backtest_params_are_validated_against_specs():
    c = client()
    h, _ = auth(c, "params")
    cases = [
        {"fastPeriod": 0, "slowPeriod": 30},
        {"fastPeriod": "abc", "slowPeriod": 30},
        {"fastPeriod": 10, "slowPeriod": 30, "nope": 1},
        {"fastPeriod": 10.5, "slowPeriod": 30},
    ]
    for params in cases:
        r = c.post(
            "/api/v1/backtests",
            json={
                "templateId": "ma-crossover",
                "asset": "AAPL",
                "from": "2022-01-01",
                "to": "2022-12-31",
                "params": params,
            },
            headers=h,
        )
        assert r.status_code == 422, (params, r.status_code, r.text)
        assert r.json()["code"] == "BAD_INPUT"
