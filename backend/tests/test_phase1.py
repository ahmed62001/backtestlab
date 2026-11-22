"""Phase 1 gates: vendor import, golden match, denylist, synthetic boot-refuse."""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

import pandas as pd


def test_app_imports_vendor_code():
    import inspect

    import app.main as M

    src = inspect.getsource(M) + pathlib.Path("app/adapter.py").read_text()
    assert "GlobalEquityEngine" in src
    assert "backtest.engines.global_equity" in src
    from app.adapter import VibeTradingEngine

    assert hasattr(VibeTradingEngine, "run")


def test_golden_vendor_vs_adapter_match():
    import tempfile
    from pathlib import Path

    from app.adapter import VibeTradingEngine
    from app.signals import FrameLoader, TemplateSignals
    from backtest.engines.global_equity import GlobalEquityEngine

    df = pd.read_csv("tests/fixtures/AAPL.csv", index_col=0, parse_dates=True)
    cfg = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "initialCapital": 10000,
        "commissionPct": 0.0,
        "slippagePct": 0.05,
        "params": {"fastPeriod": 10, "slowPeriod": 30},
    }
    vcfg = {
        "codes": ["AAPL"],
        "start_date": str(df.index[0].date()),
        "end_date": str(df.index[-1].date()),
        "interval": "1D",
        "initial_cash": 10000,
        "leverage": 1.0,
        "us_commission": 0.0005,
        "slippage_us": 0.0005,
    }
    with tempfile.TemporaryDirectory() as td:
        direct = GlobalEquityEngine(dict(vcfg)).run_backtest(
            dict(vcfg),
            FrameLoader(df),
            TemplateSignals("ma-crossover", {"fastPeriod": 10, "slowPeriod": 30}),
            Path(td),
        )
    raw, _eng = VibeTradingEngine().run(cfg, df)
    for k in ("total_return", "sharpe", "trade_count", "max_drawdown", "final_value"):
        assert abs(float(direct[k]) - float(raw[k])) < 1e-9, (k, direct[k], raw[k])


def test_denylist_rejects_leverage_short_and_derivatives():
    import pandas as pd
    from app.adapter import EngineRejectedError, VibeTradingEngine

    df = pd.read_csv("tests/fixtures/AAPL.csv", index_col=0, parse_dates=True)
    bad_cfgs = [
        {"templateId": "ma-crossover", "asset": "AAPL", "leverage": 5},
        {"templateId": "ma-crossover", "asset": "AAPL", "short": True},
        {"templateId": "futures-x", "asset": "AAPL"},
        {"templateId": "ma-crossover", "asset": "AAPL", "margin": True},
    ]
    for c in bad_cfgs:
        try:
            VibeTradingEngine().run(dict(c), df)
        except EngineRejectedError:
            continue
        raise AssertionError(f"not rejected: {c}")


def test_spot_crypto_is_allowed_by_adapter():
    """Crypto spot is an advertised product capability since Phase 14.

    The adapter still enforces spot-only: leverage/short/derivatives remain
    rejected, while registered crypto spot instruments pass validation.
    """
    from app.adapter import _reject_if_banned

    for asset in ("BTC-USD", "ETH-USD", "BTC-USDT", "ETH-USDT"):
        _reject_if_banned(
            {
                "templateId": "ma-crossover",
                "asset": asset,
                "leverage": 1,
                "short": False,
                "margin": False,
                "params": {},
            }
        )


def test_production_boot_refuses_local_mode():
    import subprocess

    r = subprocess.run(
        ["python3", "-c", "import app.engine"],
        capture_output=True,
        text=True,
        cwd=".",
        check=False,
        env={**os.environ, "ENV": "production", "ENGINE_MODE": "local"},
    )
    assert r.returncode != 0 and "REFUSE_BOOT" in (r.stdout + r.stderr)


def test_unknown_engine_mode_refuses_boot():
    import subprocess

    r = subprocess.run(
        ["python3", "-c", "import app.engine"],
        capture_output=True,
        text=True,
        cwd=".",
        check=False,
        env={**os.environ, "ENV": "dev", "ENGINE_MODE": "test"},
    )
    assert r.returncode != 0 and "REFUSE_BOOT" in (r.stdout + r.stderr)
