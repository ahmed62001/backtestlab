"""Phase 1 runtime-proof gates (2026-10-19):

- spy test: ENGINE_MODE=vendor MUST actually call the vendor entry point
  (backtest.engines.global_equity.GlobalEquityEngine.run_backtest);
- no-silent-fallback: if the vendor engine is unavailable, the request fails
  with ENGINE_UNAVAILABLE and the local imitation is NEVER used;
- golden test: same strategy + data + params through the vendor code directly
  and through our API must match (total return, max drawdown, trades, Sharpe)
  within a tight tolerance (fixtures in tests/golden/);
- look-ahead bias: signal at bar t only uses data up to t, execution at t+1
  (vendor _align shifts signals by exactly one bar).
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

import pandas as pd

BASE = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = json.loads((BASE / "tests" / "golden" / "api_golden.json").read_text())


def _client():
    from app.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app(), raise_server_exceptions=False)


def _auth(c):
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Spy", "email": "spy-runtime@t.com", "password": "password123"},
    )
    if r.status_code != 201:
        r = c.post(
            "/api/v1/auth/login", json={"email": "spy-runtime@t.com", "password": "password123"}
        )
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_vendor_entry_point_is_actually_called(monkeypatch):
    """Spy on the REAL vendor entry point; an API run must call it exactly once."""
    import backtest.engines.global_equity as ge

    RealGE = ge.GlobalEquityEngine
    calls = {"n": 0}

    class SpyGE(RealGE):
        def run_backtest(self, *a, **k):
            calls["n"] += 1
            return super().run_backtest(*a, **k)

    monkeypatch.setattr(ge, "GlobalEquityEngine", SpyGE)
    c = _client()
    h = _auth(c)
    rb = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "from": "2022-01-01",
            "to": "2022-12-31",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {"fastPeriod": 10, "slowPeriod": 30},
        },
        headers=h,
    )
    assert rb.status_code == 201, rb.text
    assert calls["n"] == 1, f"vendor run_backtest called {calls['n']} times"
    eng = rb.json()["engine"]
    assert eng["mode"] == "vendor"
    assert eng["engineName"] == "vibe-trading:GlobalEquityEngine"
    assert eng["vendorCommit"] == "c546e877274e7d36056c042808e1a875d9081eb9"
    assert eng["vendorVersionOrRef"]


def test_vendor_failure_fails_request_no_silent_fallback(monkeypatch):
    """ENGINE_MODE=vendor + broken vendor => 503 ENGINE_UNAVAILABLE, never the
    local imitation."""
    from app import adapter

    def boom():
        raise adapter.VendorUnavailableError(
            "vendor engine unavailable: simulated missing vendor tree"
        )

    monkeypatch.setattr(adapter, "load_vendor_engine", boom)
    c = _client()
    h = _auth(c)
    before = c.get("/api/v1/backtests", headers=h).json()["total"]
    rb = c.post(
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
    assert rb.status_code == 503, rb.text
    body = rb.json()
    assert body["code"] == "ENGINE_UNAVAILABLE"
    assert "vendor" in body["message"].lower()
    # no result was stored: the local engine must not have run
    after = c.get("/api/v1/backtests", headers=h).json()["total"]
    assert after == before, (before, after)


def test_golden_api_matches_vendor_direct():
    """Same strategy + data + params: vendor direct vs our API, tight tolerance."""
    from app.adapter import VibeTradingEngine

    cfg = dict(GOLDEN["config"])
    tol = float(GOLDEN["tolerance"])
    df = pd.read_csv(BASE / "tests" / "golden" / "golden_bars.csv", index_col=0, parse_dates=True)
    raw, _eng = VibeTradingEngine().run(cfg, df)
    direct = {
        "totalReturnPct": round(float(raw["total_return"]) * 100, 2),
        "maxDrawdownPct": round(float(raw["max_drawdown"]) * 100, 2),
        "trades": int(raw["trade_count"]),
        "sharpe": round(float(raw["sharpe"]), 2),
    }
    stored = GOLDEN["vendor_direct"]
    c = _client()
    h = _auth(c)
    rb = c.post("/api/v1/backtests", json=cfg, headers=h)
    assert rb.status_code == 201, rb.text
    api = rb.json()
    for k in ("totalReturnPct", "maxDrawdownPct", "trades", "sharpe"):
        assert abs(direct[k] - stored[k]) <= tol, (k, direct[k], stored[k])
        assert abs(api[k] - GOLDEN["api"][k]) <= tol, (k, api[k], GOLDEN["api"][k])
        assert abs(api[k] - direct[k]) <= tol, (k, api[k], direct[k])
    assert api["engine"]["mode"] == "vendor"


def test_lookahead_signal_causality():
    """Signal at bar t must only use data up to bar t (truncation invariance)."""
    from app.signals import signal_series

    df = pd.read_csv(BASE / "tests" / "fixtures" / "AAPL.csv", index_col=0, parse_dates=True)
    cases = [
        ("ma-crossover", {"fastPeriod": 10, "slowPeriod": 30}),
        ("breakout", {"lookback": 20, "bufferPct": 0.5}),
        ("rsi", {"rsiPeriod": 14, "oversold": 30, "overbought": 70}),
        ("momentum", {"lookback": 60}),
    ]
    for tid, params in cases:
        full = signal_series(tid, df, params)
        for k in (60, 90, 120, len(df) - 1):
            trunc = signal_series(tid, df.iloc[: k + 1], params)
            assert trunc.iloc[k] == full.iloc[k], (tid, k)


def test_lookahead_execution_is_next_bar():
    """The vendor engine executes the signal of bar t at bar t+1: its _align()
    shifts signals by exactly one bar and zeroes bar 0."""
    from app.signals import signal_series
    from backtest.engines.base import _align

    df = pd.read_csv(BASE / "tests" / "fixtures" / "AAPL.csv", index_col=0, parse_dates=True)
    sig = signal_series("ma-crossover", df, {"fastPeriod": 10, "slowPeriod": 30})
    _dates, _close, _close_val, pos, _ret = _align({"AAPL": df}, {"AAPL": sig}, ["AAPL"])
    assert len(pos) == len(df)
    assert float(pos.iloc[0, 0]) == 0.0, "bar 0 must be flat (no look-ahead)"
    for t in range(1, len(pos)):
        expected = float(sig.iloc[t - 1])
        expected = max(min(expected, 1.0), -1.0)
        assert abs(float(pos.iloc[t, 0]) - expected) < 1e-12, f"bar {t}"


def test_local_mode_runs_synthetic_only_when_explicit():
    """ENGINE_MODE=local is the ONLY way to run the local imitation."""
    import subprocess

    script = (
        "import os\n"
        "try:\n"
        "    os.remove('/tmp/bt_localmode.db')\n"
        "except OSError:\n"
        "    pass\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "c = TestClient(create_app(), raise_server_exceptions=False)\n"
        "r = c.post('/api/v1/auth/register', json={'name':'Loc',"
        "'email':'loc@t.com','password':'password123'})\n"
        "h = {'Authorization': 'Bearer ' + r.json()['token']}\n"
        "rb = c.post('/api/v1/backtests', json={'templateId':'ma-crossover',"
        "'asset':'AAPL','initialCapital':10000,'feePct':0.1,'params':{}},"
        "headers=h)\n"
        "d = rb.json()\n"
        "print('STATUS', rb.status_code)\n"
        "print('MODE', d.get('engine',{}).get('mode'))\n"
        "print('SYN', any(w['code']=='SYNTHETIC_DATA' for w in d.get('warnings',[])))\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(BASE),
        env={
            **os.environ,
            "ENGINE_MODE": "local",
            "ENV": "dev",
            "DATABASE_URL": "sqlite:////tmp/bt_localmode.db",
        },
    )
    assert r.returncode == 0, r.stderr
    assert "STATUS 201" in r.stdout, r.stdout
    assert "MODE local" in r.stdout, r.stdout
    assert "SYN True" in r.stdout, r.stdout


def test_all_templates_are_vendor_backed():
    """Every shipped template must run through the real vendor engine."""
    from app.adapter import VibeTradingEngine
    from app.synthetic_engine import TEMPLATES

    df = pd.read_csv(BASE / "tests" / "fixtures" / "AAPL.csv", index_col=0, parse_dates=True)
    not_backed = []
    for t in TEMPLATES:
        cfg = {
            "templateId": t["id"],
            "asset": "AAPL",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": dict(t.get("defaultParams") or {}),
        }
        try:
            raw, _eng = VibeTradingEngine().run(dict(cfg), df)
            assert "total_return" in raw and "trade_count" in raw
        except Exception as e:  # noqa: BLE001
            not_backed.append(f"{t['id']}: {e}")
    assert not not_backed, "NOT VENDOR-BACKED: " + "; ".join(not_backed)
    assert len(TEMPLATES) == 11
