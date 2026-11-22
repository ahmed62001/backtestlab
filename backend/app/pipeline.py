"""Normalize vendor metrics dict -> API contract result shape."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .engine import engine_block
from .spot_engine import (
    INTRADAY_INTERVALS,
    CostConfig,
    compute_bars_per_year,
    compute_independent_metrics,
    normalize_interval,
    resolve_market_profile,
)


def _naive_utc_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx


def _benchmark_curve(bars: pd.DataFrame, eq: pd.Series, capital: float) -> pd.Series:
    """Buy-and-hold value of the underlying, aligned to the equity timestamps."""
    n = len(eq)
    if n == 0:
        return pd.Series(dtype=float)
    idx = _naive_utc_index(eq.index)
    if bars is None or len(bars) == 0 or "close" not in bars.columns:
        return pd.Series([capital] * n, index=idx)
    close = bars["close"].astype(float).copy()
    close.index = _naive_utc_index(close.index)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    aligned = close.reindex(idx, method="ffill").bfill()
    base = float(aligned.iloc[0]) if len(aligned) else float("nan")
    if len(aligned) != n or not math.isfinite(base) or base <= 0 or aligned.isna().any():
        return pd.Series([capital] * n, index=idx)
    return capital * aligned / base


def normalize(
    raw: dict[str, Any],
    eng,
    cfg: dict[str, Any],
    bars: pd.DataFrame,
    prov: dict[str, Any],
    extra_warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    capital = float(cfg.get("initialCapital", 10000))
    fee_pct = float(cfg.get("feePct", 0.1))
    asset = str(cfg.get("asset", "AAPL"))
    interval = normalize_interval(cfg.get("interval", "1D"))
    is_intraday = interval in INTRADAY_INTERVALS

    profile = getattr(eng, "profile", None) or resolve_market_profile(asset)
    cost_cfg = getattr(eng, "cost_cfg", None) or CostConfig.from_cfg(cfg, profile)
    bars_per_year = compute_bars_per_year(profile, interval)

    # Preserve the client's original symbol spelling alongside the canonical
    # provider symbol (e.g. BTC/USDT requested -> BTC-USDT executed).
    prov = dict(prov)
    if cfg.get("requestedSymbol"):
        prov["requested_symbol"] = str(cfg["requestedSymbol"])
    prov["interval"] = interval
    prov["marketProfile"] = profile.key
    prov["assetClass"] = profile.asset_class
    prov["currency"] = profile.currency
    prov["exchange"] = profile.exchange
    prov["barsCount"] = int(len(bars)) if bars is not None else 0
    if bars is not None and len(bars) > 0:
        b_idx = _naive_utc_index(bars.index)
        prov["actualPeriod"] = {
            "from": b_idx[0].strftime("%Y-%m-%dT%H:%M:%SZ" if is_intraday else "%Y-%m-%d"),
            "to": b_idx[-1].strftime("%Y-%m-%dT%H:%M:%SZ" if is_intraday else "%Y-%m-%d"),
        }
        prov["lastBar"] = b_idx[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    prov["executionAssumptions"] = {
        "signalShiftBars": 1,
        "fillPrice": "next_bar_open",
        "spotOnly": True,
        "longOnly": True,
        "intrabarOrder": "stop_loss_first",
        "barsPerYear": bars_per_year,
    }

    snaps = eng.equity_snapshots
    eq = pd.Series([s.equity for s in snaps], index=[s.timestamp for s in snaps])
    eq.index = _naive_utc_index(eq.index)
    bench_curve = _benchmark_curve(bars, eq, capital)

    date_fmt = "%Y-%m-%dT%H:%M:%SZ" if is_intraday else "%Y-%m-%d"
    equity = []
    peak = capital
    for ts, val, bv in zip(eq.index, eq.values, bench_curve.values, strict=False):
        peak = max(peak, float(val))
        dd = (float(val) - peak) / peak * 100 if peak else 0.0
        d = pd.Timestamp(ts)
        equity.append(
            {
                "date": d.strftime(date_fmt),
                "strategy": round(float(val), 2),
                "benchmark": round(float(bv), 2),
                "drawdown": round(dd, 2),
            }
        )

    px_prec = max(2, profile.price_precision)
    qty_prec = max(4, profile.qty_precision)
    exit_reasons: list[str] = list(getattr(eng, "trade_exit_reasons", []) or [])

    tlist = []
    for i, t in enumerate(getattr(eng, "trades", []) or []):
        d = getattr(t, "exit_time", None) or getattr(t, "entry_time", None)
        px = float(getattr(t, "exit_price", 0.0) or 0.0)
        entry_px = float(getattr(t, "entry_price", 0.0) or 0.0)
        pnl = float(getattr(t, "pnl", 0.0) or 0.0)
        direction = int(getattr(t, "direction", 1) or 1)
        qty = float(getattr(t, "size", 0.0) or 0.0)
        pnl_pct = getattr(t, "pnl_pct", None)
        if pnl_pct is None:
            margin = float(getattr(t, "entry_margin", 0.0) or 0.0)
            ret_pct = (pnl / margin * 100) if margin else (pnl / capital * 100 if capital else 0.0)
        else:
            ret_pct = float(pnl_pct)
        reason = exit_reasons[i] if i < len(exit_reasons) else "signal"
        tlist.append(
            {
                "id": f"tr-{i + 1}",
                "date": pd.Timestamp(d).strftime(date_fmt) if d is not None else "",
                "side": "buy" if direction < 0 else "sell",
                "direction": "short" if direction < 0 else "long",
                "entryPrice": round(entry_px, px_prec),
                "price": round(px, px_prec),
                "qty": round(qty, qty_prec),
                "pnl": round(pnl, 2),
                "returnPct": round(ret_pct, 4),
                "exitReason": reason,
            }
        )

    # Realized fees from fill_records / trades (fall back to feePct estimate
    # only for mocked unit-test engines that omit fill_records)
    fills = getattr(eng, "fill_records", []) or []
    realized_commission = sum(float(getattr(f, "commission", 0.0) or 0.0) for f in fills)
    if realized_commission == 0.0:
        realized_commission = sum(
            float(getattr(t, "commission", 0.0) or 0.0) for t in (getattr(eng, "trades", []) or [])
        )
    one_way_slip_rate = (cost_cfg.slippage_pct + cost_cfg.spread_pct / 2.0) / 100.0
    realized_slippage = sum(
        abs(float(getattr(f, "notional", 0.0) or 0.0)) * one_way_slip_rate
        for f in fills
    )
    ntr_raw = int(raw.get("trade_count", len(tlist)))
    if fills:
        total_estimated_fees = round(realized_commission + realized_slippage, 2)
    else:
        total_estimated_fees = round(ntr_raw * fee_pct / 100 * capital, 2)

    ind = compute_independent_metrics(
        equity_values=[float(v) for v in eq.values],
        timestamps=list(eq.index),
        trades=tlist,
        initial_capital=capital,
        bars_per_year=bars_per_year,
        benchmark_values=[float(v) for v in bench_curve.values],
    )
    ntr = ntr_raw if not tlist and ntr_raw > 0 else ind["trades"]
    if raw.get("benchmark_return") is not None:
        bench_ret_pct = round(float(raw["benchmark_return"]) * 100.0, 2)
        ind["benchmarkReturnPct"] = bench_ret_pct
        ind["vsBuyHoldPct"] = round(ind["totalReturnPct"] - bench_ret_pct, 2)

    months: dict[str, float] = {}
    for ts, v in eq.items():
        k = pd.Timestamp(ts).strftime("%Y-%m")
        months[k] = float(v)
    keys = sorted(months)
    monthly = []
    prev = capital
    for k in keys:
        y, m = k.split("-")
        val_m = ((months[k] - prev) / prev * 100) if prev else 0.0
        monthly.append({"year": int(y), "month": int(m), "value": round(val_m, 2)})
        prev = months[k]

    warns = list(extra_warnings or [])
    if ntr < 10:
        warns.append({"code": "FEW_TRADES"})
    if bars is not None and len(bars) < 60:
        warns.append({"code": "SHORT_HISTORY"})
    if not (cfg.get("validation") and cfg["validation"].get("mode") == "split"):
        warns.append({"code": "NO_OUT_OF_SAMPLE"})
    warns.append({"code": "COSTS_ASSUMED"})
    warns.append({"code": "SURVIVORSHIP_BIAS_POSSIBLE"})
    seen, uniq = set(), []
    for x in warns:
        if x["code"] not in seen:
            seen.add(x["code"])
            uniq.append(x)

    return {
        "templateId": str(cfg.get("templateId", "ma-crossover")),
        "asset": asset,
        "interval": interval,
        "totalReturnPct": ind["totalReturnPct"],
        "annualizedReturnPct": ind["annualizedReturnPct"],
        "volatilityPct": ind["volatilityPct"],
        "maxDrawdownPct": ind["maxDrawdownPct"],
        "maxDrawdownDurationBars": ind["maxDrawdownDurationBars"],
        "sharpe": ind["sharpe"],
        "sortino": ind["sortino"],
        "winRatePct": ind["winRatePct"],
        "profitFactor": ind["profitFactor"],
        "avgWin": ind["avgWin"],
        "avgLoss": ind["avgLoss"],
        "expectancy": ind["expectancy"],
        "trades": ntr,
        "benchmarkReturnPct": ind["benchmarkReturnPct"],
        "vsBuyHoldPct": ind["vsBuyHoldPct"],
        "equity": equity,
        "monthly": monthly,
        "tradesList": tlist,
        "overfitting": ntr < 10,
        "warnings": uniq,
        "costs": {
            "feePct": fee_pct,
            "commissionPct": round(cost_cfg.commission_pct, 4),
            "slippagePct": round(cost_cfg.slippage_pct, 4),
            "spreadPct": round(cost_cfg.spread_pct, 4),
            "realizedCommission": round(realized_commission, 2),
            "realizedSlippage": round(realized_slippage, 2),
            "estimatedFees": total_estimated_fees,
            "note": "Explicit commission + slippage + half-spread per fill",
        },
        "strategyControls": {
            "stopLoss": cfg.get("stopLoss") or {"mode": "none"},
            "takeProfit": cfg.get("takeProfit") or {"mode": "none"},
            "positionSizing": cfg.get("positionSizing") or {"mode": "pct_equity", "value": 100.0},
            "validation": cfg.get("validation") or {"mode": "none"},
        },
        "provenance": prov,
        "engine": engine_block(),
    }


def _summary_metrics(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "totalReturnPct": res["totalReturnPct"],
        "annualizedReturnPct": res["annualizedReturnPct"],
        "volatilityPct": res["volatilityPct"],
        "sharpe": res["sharpe"],
        "sortino": res["sortino"],
        "maxDrawdownPct": res["maxDrawdownPct"],
        "winRatePct": res["winRatePct"],
        "profitFactor": res["profitFactor"],
        "trades": res["trades"],
        "benchmarkReturnPct": res["benchmarkReturnPct"],
        "vsBuyHoldPct": res["vsBuyHoldPct"],
    }


def run_and_normalize(
    cfg: dict[str, Any],
    bars: pd.DataFrame,
    prov: dict[str, Any],
    extra_warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run VibeTradingEngine and normalize, including optional chronological OOS split."""
    from .adapter import VibeTradingEngine

    eng_runner = VibeTradingEngine()
    raw, eng = eng_runner.run(cfg, bars)
    result = normalize(raw, eng, cfg, bars, prov, extra_warnings)

    val_cfg = cfg.get("validation") or {}
    if isinstance(val_cfg, dict) and val_cfg.get("mode") == "split" and len(bars) >= 30:
        b_idx = _naive_utc_index(bars.index)
        split_date_str = str(val_cfg.get("splitDate", "") or "").strip()
        if split_date_str:
            split_ts = pd.Timestamp(split_date_str)
            is_mask = b_idx < split_ts
            oos_mask = b_idx >= split_ts
            is_bars = bars.loc[is_mask]
            oos_bars = bars.loc[oos_mask]
        else:
            is_pct = float(val_cfg.get("inSamplePct", 70) or 70)
            is_pct = min(max(is_pct, 50.0), 85.0)
            split_idx = max(10, min(len(bars) - 10, int(len(bars) * (is_pct / 100.0))))
            is_bars = bars.iloc[:split_idx]
            oos_bars = bars.iloc[split_idx:]
            split_date_str = _naive_utc_index(oos_bars.index)[0].strftime("%Y-%m-%d")

        if len(is_bars) >= 10 and len(oos_bars) >= 10:
            is_raw, is_eng = eng_runner.run(cfg, is_bars)
            is_res = normalize(is_raw, is_eng, cfg, is_bars, prov, [])
            oos_raw, oos_eng = eng_runner.run(cfg, oos_bars)
            oos_res = normalize(oos_raw, oos_eng, cfg, oos_bars, prov, [])

            is_m = _summary_metrics(is_res)
            oos_m = _summary_metrics(oos_res)
            result["validation"] = {
                "mode": "split",
                "splitDate": split_date_str,
                "inSampleBars": len(is_bars),
                "outOfSampleBars": len(oos_bars),
                "inSample": is_m,
                "outOfSample": oos_m,
            }
            if is_m["sharpe"] > 1.5 and oos_m["sharpe"] < 0.3:
                result["warnings"].append(
                    {
                        "code": "POSSIBLE_OVERFIT",
                        "message": "In-sample Sharpe significantly exceeds out-of-sample Sharpe",
                    }
                )
            if oos_m["trades"] < 5:
                result["warnings"].append(
                    {
                        "code": "FEW_OOS_TRADES",
                        "message": f"Only {oos_m['trades']} trades in out-of-sample window",
                    }
                )
        else:
            result["warnings"].append(
                {
                    "code": "INSUFFICIENT_OOS_DATA",
                    "message": "Not enough bars for chronological out-of-sample split",
                }
            )
    return result
