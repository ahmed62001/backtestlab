"""Independent deterministic tests for Phase 2 (accuracy) & Phase 3 (SL/TP/sizing/OOS)."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from app.adapter import EngineRejectedError, VibeTradingEngine
from app.pipeline import normalize, run_and_normalize
from app.spot_engine import (
    compute_bars_per_year,
    compute_independent_metrics,
    normalize_interval,
    resolve_market_profile,
)


def _make_bars(
    closes: list[float],
    *,
    start: str = "2024-01-01",
    freq: str = "1D",
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=len(closes), freq=freq, tz="UTC")
    o = opens if opens is not None else closes
    h = highs if highs is not None else [max(a, b) * 1.01 for a, b in zip(o, closes, strict=True)]
    low_vals = lows if lows is not None else [min(a, b) * 0.99 for a, b in zip(o, closes, strict=True)]
    return pd.DataFrame(
        {"open": o, "high": h, "low": low_vals, "close": closes, "volume": [1000.0] * len(closes)},
        index=idx,
    )


def test_hand_calculated_buy_hold_with_explicit_costs():
    """Independently verify entry qty, commission, slippage, exit, and return."""
    # 12 flat/rising bars at 100.0 -> buy-hold enters on bar 1 open (100.0), exits on bar 11 close (120.0)
    closes = [100.0] * 11 + [120.0]
    opens = [100.0] * 12
    bars = _make_bars(closes, opens=opens, highs=closes, lows=closes)

    cfg = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "interval": "1D",
        "initialCapital": 10000.0,
        "commissionPct": 0.1,  # 0.1% one-way
        "slippagePct": 0.1,    # 0.1% one-way
        "spreadPct": 0.0,
    }
    raw, eng = VibeTradingEngine().run(cfg, bars)
    res = normalize(raw, eng, cfg, bars, {"provider": "test"})

    # Expected:
    # Entry price with 0.1% slippage = 100 * 1.001 = 100.10
    # Commission is 0.1% on notional; BaseEngine scales size to fit cash including commission.
    assert res["trades"] == 1
    tr = res["tradesList"][0]
    assert tr["entryPrice"] == pytest.approx(100.10, abs=0.01)
    # Exit at 120.0 with 0.1% slippage = 120 * 0.999 = 119.88
    assert tr["price"] == pytest.approx(119.88, abs=0.01)
    # Realized commission must be > 0 (proving US commission is NOT dropped!)
    assert res["costs"]["realizedCommission"] > 15.0
    assert res["costs"]["realizedSlippage"] > 15.0
    # Approximate net profit: ~10000/100.1 * (119.88 - 100.10) - ~22 comm ≈ 1954
    assert 1900.0 < tr["pnl"] < 2000.0
    assert res["totalReturnPct"] == pytest.approx((tr["pnl"] / 10000.0) * 100.0, abs=0.5)


def test_feepct_backward_compat_charges_both_halves():
    """When only feePct is provided, both commission (50%) and slippage (50%) are charged."""
    bars = _make_bars([100.0] * 12, opens=[100.0] * 12, highs=[100.0] * 12, lows=[100.0] * 12)
    cfg = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "initialCapital": 10000.0,
        "feePct": 1.0,  # 0.5% comm + 0.5% slip one-way -> ~2% round-trip drag
    }
    raw, eng = VibeTradingEngine().run(cfg, bars)
    res = normalize(raw, eng, cfg, bars, {"provider": "test"})
    assert res["costs"]["commissionPct"] == 0.5
    assert res["costs"]["slippagePct"] == 0.5
    assert res["costs"]["realizedCommission"] > 90.0
    assert res["totalReturnPct"] < -1.5


def test_market_profiles_and_bars_per_year():
    sa = resolve_market_profile("2222.SR")
    assert sa.currency == "SAR"
    assert sa.fractional is False
    assert compute_bars_per_year(sa, "1D") == 250

    btc = resolve_market_profile("BTC-USD")
    assert btc.asset_class == "crypto"
    assert btc.fractional is True
    assert compute_bars_per_year(btc, "1D") == 365
    assert compute_bars_per_year(btc, "1H") == 365 * 24

    fx = resolve_market_profile("EURUSD")
    assert fx.asset_class == "fx"
    assert fx.price_precision == 5
    assert compute_bars_per_year(fx, "1D") == 260


def test_intraday_1h_preserves_last_day_and_iso_timestamps():
    """1H bars on the same day must not be dropped by FrameLoader and must keep HH:MM:SSZ."""
    bars = _make_bars([100.0 + i * 0.5 for i in range(24)], start="2024-06-01 00:00", freq="1h")
    cfg = {"templateId": "buy-hold", "asset": "BTC-USD", "interval": "1H", "initialCapital": 10000.0}
    res = run_and_normalize(cfg, bars, {"provider": "test"})
    assert res["interval"] == "1H"
    assert len(res["equity"]) == 24
    assert "T" in res["equity"][0]["date"]
    assert res["provenance"]["executionAssumptions"]["barsPerYear"] == 8760


def test_unsupported_interval_rejected():
    with pytest.raises(EngineRejectedError, match="UNSUPPORTED_INTERVAL"):
        normalize_interval("2H")


def test_stop_loss_and_conservative_sl_first_rule():
    """When both SL and TP are hit in the same candle, SL must trigger first."""
    # 12 bars: entry on bar 1 at open=100. Bar 5 has low=85 (hits 10% SL at 90) AND high=125 (hits 10% TP at 110)
    closes = [100.0] * 12
    opens = [100.0] * 12
    highs = [101.0] * 12
    lows = [99.0] * 12
    highs[5] = 125.0
    lows[5] = 85.0
    bars = _make_bars(closes, opens=opens, highs=highs, lows=lows)

    cfg = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "initialCapital": 10000.0,
        "feePct": 0.0,
        "stopLoss": {"mode": "fixed_pct", "pct": 10.0},
        "takeProfit": {"mode": "fixed_pct", "pct": 10.0},
    }
    res = run_and_normalize(cfg, bars, {"provider": "test"})
    assert res["trades"] == 1
    tr = res["tradesList"][0]
    assert tr["exitReason"] == "stop_loss"
    assert tr["price"] == pytest.approx(90.0, abs=0.01)
    assert tr["pnl"] < 0


def test_take_profit_triggers_when_high_reaches_target():
    closes = [100.0] * 12
    opens = [100.0] * 12
    highs = [101.0] * 12
    lows = [99.0] * 12
    highs[4] = 116.0  # hits 15% TP at 115
    bars = _make_bars(closes, opens=opens, highs=highs, lows=lows)

    cfg = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "initialCapital": 10000.0,
        "feePct": 0.0,
        "takeProfit": {"mode": "fixed_pct", "pct": 15.0},
    }
    res = run_and_normalize(cfg, bars, {"provider": "test"})
    assert res["trades"] == 1
    tr = res["tradesList"][0]
    assert tr["exitReason"] == "take_profit"
    assert tr["price"] == pytest.approx(115.0, abs=0.01)
    assert tr["pnl"] > 0


def test_position_sizing_fixed_amount_and_risk_based():
    bars = _make_bars([100.0] * 11 + [110.0], opens=[100.0] * 12, highs=[110.0] * 12, lows=[100.0] * 12)
    cfg_fixed = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "initialCapital": 10000.0,
        "feePct": 0.0,
        "positionSizing": {"mode": "fixed_amount", "value": 2500.0, "maxAllocationPct": 100.0},
    }
    res_fixed = run_and_normalize(cfg_fixed, bars, {"provider": "test"})
    assert res_fixed["tradesList"][0]["qty"] == pytest.approx(25.0, abs=0.05)

    # Risk-based: 1% equity risk ($100) with 5% stop-loss => $2000 notional => 20 shares
    cfg_risk = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "initialCapital": 10000.0,
        "feePct": 0.0,
        "stopLoss": {"mode": "risk_based", "pct": 5.0},
        "positionSizing": {"mode": "risk_based", "value": 1.0, "maxAllocationPct": 100.0},
    }
    res_risk = run_and_normalize(cfg_risk, bars, {"provider": "test"})
    assert res_risk["tradesList"][0]["qty"] == pytest.approx(20.0, abs=0.05)


def test_metrics_edge_cases_zero_trades_and_constant_equity():
    m = compute_independent_metrics(
        equity_values=[10000.0] * 30,
        timestamps=list(pd.date_range("2024-01-01", periods=30, freq="1D")),
        trades=[],
        initial_capital=10000.0,
        bars_per_year=252,
        benchmark_values=[10000.0] * 30,
    )
    assert m["totalReturnPct"] == 0.0
    assert m["sharpe"] == 0.0
    assert m["sortino"] is None
    assert m["profitFactor"] is None
    assert m["maxDrawdownPct"] == 0.0
    assert math.isfinite(m["volatilityPct"])


def test_chronological_oos_validation():
    bars = _make_bars([100.0 + i * 0.5 for i in range(60)])
    cfg = {
        "templateId": "buy-hold",
        "asset": "AAPL",
        "initialCapital": 10000.0,
        "validation": {"mode": "split", "inSamplePct": 70},
    }
    res = run_and_normalize(cfg, bars, {"provider": "test"})
    assert "validation" in res
    assert res["validation"]["inSampleBars"] == 42
    assert res["validation"]["outOfSampleBars"] == 18
    assert "sharpe" in res["validation"]["inSample"]
    assert "totalReturnPct" in res["validation"]["outOfSample"]
    assert all(w["code"] != "NO_OUT_OF_SAMPLE" for w in res["warnings"])
