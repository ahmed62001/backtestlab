"""Phase 2/3 gates: data layer offline, honesty (look-ahead, metrics, warnings)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

import contextlib
from typing import ClassVar

import pandas as pd


def test_real_backtest_end_to_end_with_provenance():
    import os

    os.environ["DATABASE_URL"] = "sqlite:////tmp/bt_p23.db"
    with contextlib.suppress(OSError):
        pathlib.Path("/tmp/bt_p23.db").unlink()
    from app.main import create_app
    from fastapi.testclient import TestClient

    c = TestClient(create_app(), raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "P23", "email": "p23@t.com", "password": "password123"},
    )
    if r.status_code != 201:
        r = c.post("/api/v1/auth/login", json={"email": "p23@t.com", "password": "password123"})
    assert r.status_code in (200, 201), r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    rb = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {"fastPeriod": 10, "slowPeriod": 30},
        },
        headers=h,
    )
    assert rb.status_code == 201, rb.text
    bid = rb.json()["id"]
    d = c.get(f"/api/v1/backtests/{bid}", headers=h).json()
    assert d["provenance"]["provider"] == "local", d["provenance"]
    assert d["provenance"]["bars"] >= 100
    assert d["engine"]["mode"] == "vendor"
    assert d["engine"]["engineName"] == "vibe-trading:GlobalEquityEngine"
    assert d["engine"]["vendorCommit"] == "c546e877274e7d36056c042808e1a875d9081eb9"
    assert d["engine"]["vendorVersionOrRef"]
    codes = {w["code"] for w in d["warnings"]}
    assert {"COSTS_ASSUMED", "DATA_DEV_SOURCE"} <= codes, codes
    assert len(d["equity"]) >= 100


def test_offline_no_network_in_provider_path():
    import socket

    real = socket.socket.connect
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(
        OSError("network blocked in test")
    )
    try:
        from app.data import LocalCsvProvider

        res = LocalCsvProvider().fetch("AAPL")
        assert len(res.frame) > 0
    finally:
        socket.socket.connect = real


def test_lookahead_signal_at_t_executes_at_t_plus_1():
    """Construct a series where a look-ahead bug prints an impossible return.
    Prices: flat 100 then a single +50% jump on day 20. A signal computed from
    the jump, if executed SAME-bar, captures the jump; next-bar-open must not.
    We assert the vendor _align shift: signal row for the jump bar maps to a
    position that only starts the NEXT bar."""
    import numpy as np
    from app.signals import signal_series

    idx = pd.date_range("2022-01-03", periods=40, freq="B")
    px = np.full(40, 100.0)
    px[20:] = 150.0
    df = pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 1000}, index=idx)
    sig = signal_series("breakout", df, {"lookback": 5, "bufferPct": 0.0})
    # breakout signal first fires ON the jump bar (index 20), never before
    assert sig.iloc[20] == 1.0
    assert (sig.iloc[:20] == 0.0).all()
    # vendor _align shifts by 1: emulate and check execution misses the jump
    shifted = sig.shift(1).fillna(0.0)
    assert shifted.iloc[20] == 0.0 and shifted.iloc[21] == 1.0
    # end-to-end through the real vendor: entry price must be the bar AFTER
    # the jump (150), not the pre-jump close (100)
    import tempfile
    from pathlib import Path

    from app.signals import FrameLoader, TemplateSignals
    from backtest.engines.global_equity import GlobalEquityEngine

    vcfg = {
        "codes": ["T"],
        "start_date": str(idx[0].date()),
        "end_date": str(idx[-1].date()),
        "interval": "1D",
        "initial_cash": 10000,
        "leverage": 1.0,
    }
    with tempfile.TemporaryDirectory() as td:
        eng = GlobalEquityEngine(dict(vcfg))
        eng.run_backtest(
            dict(vcfg),
            FrameLoader(df),
            TemplateSignals("breakout", {"lookback": 5, "bufferPct": 0.0}),
            Path(td),
        )
    fills = eng.fill_records
    assert fills, "expected at least one fill"
    assert float(fills[0].execution_price) >= 149.0, fills[0].execution_price


def test_metrics_normalizer_hand_computed():
    import pandas as pd
    from app.pipeline import normalize

    idx = pd.date_range("2022-01-03", periods=5, freq="B")
    eq = [10000, 10100, 10201, 10000, 10300.0]

    class S:
        def __init__(self, ts, e):
            self.timestamp = ts
            self.equity = e

    class T:
        def __init__(self, pnl, px, d):
            self.pnl = pnl
            self.exit_price = px
            self.exit_time = d
            self.entry_time = d

    class E:
        equity_snapshots: ClassVar[list] = [S(t, v) for t, v in zip(idx, eq, strict=False)]
        trades: ClassVar[list] = [T(200.0, 102.0, idx[2]), T(-100.0, 101.0, idx[4])]

    raw = {
        "total_return": (eq[-1] / 10000 - 1),
        "max_drawdown": -0.0197,
        "sharpe": 1.5,
        "trade_count": 2,
        "benchmark_return": 0.01,
    }
    bars = pd.DataFrame({"close": eq}, index=idx)
    n = normalize(
        raw,
        E(),
        {"templateId": "buy-hold", "asset": "AAPL", "initialCapital": 10000, "feePct": 0.1},
        bars,
        {"provider": "local"},
        [],
    )
    assert n["totalReturnPct"] == 3.0
    assert n["trades"] == 2
    assert n["winRatePct"] == 50.0
    assert n["vsBuyHoldPct"] == 2.0
    assert "COSTS_ASSUMED" in {w["code"] for w in n["warnings"]}


def test_no_exec_eval_compile_in_app():
    import pathlib
    import re

    bad = []
    for p in pathlib.Path("app").glob("*.py"):
        src = p.read_text()
        # Attribute calls such as ``re.compile(...)`` are the legitimate regex
        # factory; the guard targets the dynamic-code builtins only.
        for m in re.finditer(r"(?<!\.)\b(exec|eval|compile)\s*\(", src):
            bad.append(f"{p}:{m.group(0)}")
    assert not bad, bad


ALL_TEMPLATES = [
    "ma-crossover",
    "rsi",
    "breakout",
    "mean-reversion",
    "buy-hold",
    "ema-cross",
    "macd",
    "bollinger",
    "donchian",
    "dca",
    "momentum",
]


def test_every_template_runs_on_real_fixture_data():
    from app.adapter import VibeTradingEngine
    from app.data import LocalCsvProvider

    df = LocalCsvProvider().fetch("AAPL").frame
    ok = {}
    for tid in ALL_TEMPLATES:
        raw, _eng = VibeTradingEngine().run(
            {
                "templateId": tid,
                "asset": "AAPL",
                "initialCapital": 10000,
                "feePct": 0.1,
                "params": {},
            },
            df,
        )
        assert isinstance(raw["trade_count"], int)
        ok[tid] = raw["trade_count"]
    assert len(ok) == 11, ok


def test_banned_terms_scan_all_user_strings():
    banned = [
        "buy now",
        "sell now",
        "guaranteed",
        "sure profit",
        "risk-free",
        "will earn",
        "اشتر الآن",
        "ربح مضمون",
        "بدون مخاطر",
    ]
    import json

    from app import synthetic_engine as E

    blob = json.dumps(E.TEMPLATES + [E.DISCLAIMER]).lower()
    assert not any(b in blob for b in banned), "banned term in templates"
