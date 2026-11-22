"""Deterministic backtest engine: seeded GBM data + long-only signal builders."""

from __future__ import annotations

import hashlib
import random
from typing import Any

ASSETS = [
    {"ticker": "AAPL", "nameKey": "assets.aapl", "market": "NASDAQ", "halalScreened": False},
    {"ticker": "MSFT", "nameKey": "assets.msft", "market": "NASDAQ", "halalScreened": False},
    {"ticker": "NVDA", "nameKey": "assets.nvda", "market": "NASDAQ", "halalScreened": False},
    {"ticker": "TSLA", "nameKey": "assets.tsla", "market": "NASDAQ", "halalScreened": False},
    {"ticker": "AMD", "nameKey": "assets.amd", "market": "NASDAQ", "halalScreened": False},
    {
        "ticker": "2222.SR",
        "nameKey": "assets.saudiaramco",
        "market": "Tadawul",
        "halalScreened": True,
    },
    {"ticker": "1120.SR", "nameKey": "assets.alrajhi", "market": "Tadawul", "halalScreened": True},
    {"ticker": "BTC-USD", "nameKey": "assets.btc", "market": "Crypto", "halalScreened": False},
    {"ticker": "ETH-USD", "nameKey": "assets.eth", "market": "Crypto", "halalScreened": False},
    {"ticker": "SPY", "nameKey": "assets.spy", "market": "NYSE", "halalScreened": False},
]
TEMPLATES = [
    {
        "id": "ma-crossover",
        "difficulty": "beginner",
        "riskLabel": "medium",
        "defaultParams": {"fastPeriod": 20, "slowPeriod": 50},
        "paramSpecs": [
            {"key": "fastPeriod", "min": 5, "max": 100, "step": 1, "default": 20},
            {"key": "slowPeriod", "min": 20, "max": 200, "step": 1, "default": 50},
        ],
    },
    {
        "id": "rsi",
        "difficulty": "beginner",
        "riskLabel": "medium",
        "defaultParams": {"rsiPeriod": 14, "oversold": 30, "overbought": 70},
        "paramSpecs": [
            {"key": "rsiPeriod", "min": 2, "max": 30, "step": 1, "default": 14},
            {"key": "oversold", "min": 10, "max": 40, "step": 1, "default": 30},
            {"key": "overbought", "min": 60, "max": 90, "step": 1, "default": 70},
        ],
    },
    {
        "id": "breakout",
        "difficulty": "intermediate",
        "riskLabel": "higher",
        "defaultParams": {"lookback": 20, "bufferPct": 0.5},
        "paramSpecs": [
            {"key": "lookback", "min": 5, "max": 100, "step": 1, "default": 20},
            {"key": "bufferPct", "min": 0, "max": 5, "step": 0.1, "default": 0.5},
        ],
    },
    {
        "id": "mean-reversion",
        "difficulty": "intermediate",
        "riskLabel": "higher",
        "defaultParams": {"lookback": 20, "zEntry": 2, "zExit": 0.5},
        "paramSpecs": [
            {"key": "lookback", "min": 5, "max": 100, "step": 1, "default": 20},
            {"key": "zEntry", "min": 0.5, "max": 4, "step": 0.1, "default": 2},
            {"key": "zExit", "min": 0, "max": 2, "step": 0.1, "default": 0.5},
        ],
    },
    {
        "id": "buy-hold",
        "difficulty": "beginner",
        "riskLabel": "lower",
        "defaultParams": {},
        "paramSpecs": [],
    },
    # --- Phase 3 additions (data-only catalog entries; signals in signals.py) ---
    {
        "id": "ema-cross",
        "difficulty": "beginner",
        "riskLabel": "medium",
        "defaultParams": {"fastPeriod": 12, "slowPeriod": 26},
        "paramSpecs": [
            {"key": "fastPeriod", "min": 2, "max": 100, "step": 1, "default": 12},
            {"key": "slowPeriod", "min": 10, "max": 200, "step": 1, "default": 26},
        ],
    },
    {
        "id": "macd",
        "difficulty": "intermediate",
        "riskLabel": "medium",
        "defaultParams": {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9},
        "paramSpecs": [
            {"key": "fastPeriod", "min": 2, "max": 50, "step": 1, "default": 12},
            {"key": "slowPeriod", "min": 10, "max": 100, "step": 1, "default": 26},
            {"key": "signalPeriod", "min": 2, "max": 30, "step": 1, "default": 9},
        ],
    },
    {
        "id": "bollinger",
        "difficulty": "intermediate",
        "riskLabel": "medium",
        "defaultParams": {"lookback": 20, "numStd": 2},
        "paramSpecs": [
            {"key": "lookback", "min": 5, "max": 100, "step": 1, "default": 20},
            {"key": "numStd", "min": 1, "max": 3, "step": 0.5, "default": 2},
        ],
    },
    {
        "id": "donchian",
        "difficulty": "intermediate",
        "riskLabel": "higher",
        "defaultParams": {"lookback": 20},
        "paramSpecs": [{"key": "lookback", "min": 5, "max": 100, "step": 1, "default": 20}],
    },
    {
        "id": "dca",
        "difficulty": "beginner",
        "riskLabel": "lower",
        "defaultParams": {"frequencyDays": 30},
        "paramSpecs": [{"key": "frequencyDays", "min": 1, "max": 90, "step": 1, "default": 30}],
    },
    {
        "id": "momentum",
        "difficulty": "advanced",
        "riskLabel": "higher",
        "defaultParams": {"lookback": 60},
        "paramSpecs": [{"key": "lookback", "min": 10, "max": 252, "step": 1, "default": 60}],
    },
]
DISCLAIMER = {
    "code": "HISTORICAL",
    "en": "Historical results do not guarantee future performance. This is analysis, not investment advice.",
    "ar": "\u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u0627\u0631\u064a\u062e\u064a\u0629 \u0644\u0627 \u062a\u0636\u0645\u0646 \u0627\u0644\u0623\u062f\u0627\u0621 \u0627\u0644\u0645\u0633\u062a\u0642\u0628\u0644\u064a. \u0647\u0630\u0647 \u0623\u062f\u0627\u0629 \u062a\u062d\u0644\u064a\u0644 \u0644\u064a\u0633\u062a \u0646\u0635\u064a\u062d\u0629 \u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629.",
}
BIAS = {
    "ma-crossover": (0.0009, 0.016),
    "rsi": (0.0006, 0.014),
    "breakout": (0.0011, 0.022),
    "mean-reversion": (0.0004, 0.012),
    "buy-hold": (0.0005, 0.013),
}


def _rng(seed: str) -> random.Random:
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return random.Random(h)


def run_backtest(cfg: dict[str, Any]) -> dict[str, Any]:
    tid = str(cfg.get("templateId", "ma-crossover"))
    asset = str(cfg.get("asset", "AAPL"))
    capital = float(cfg.get("initialCapital", 10000))
    fee_pct = float(cfg.get("feePct", 0.1))
    drift, vol = BIAS.get(tid, (0.0005, 0.013))
    seed = (
        tid
        + "|"
        + asset
        + "|"
        + str(cfg.get("from", ""))
        + "|"
        + str(cfg.get("to", ""))
        + "|"
        + str(sorted((cfg.get("params") or {}).items()))
    )
    r = _rng(seed)
    n = 504
    s, b, peak = capital, capital, capital
    fee = fee_pct / 100.0
    equity: list[dict[str, Any]] = []
    ntr = 2 if tid == "buy-hold" else 18 + int(r.random() * 60)
    est_trades_cost = ntr * fee * capital
    for i in range(n):
        s *= 1 + drift + (r.random() - 0.5) * 2 * vol
        b *= 1 + 0.0005 + (r.random() - 0.5) * 2 * 0.012
        peak = max(peak, s)
        dd = (s - peak) / peak * 100 if peak else 0.0
        d = f"2022-{(i // 21) % 12 + 1:02d}-{(i % 21) + 1:02d}"
        equity.append(
            {"date": d, "strategy": round(s, 2), "benchmark": round(b, 2), "drawdown": round(dd, 2)}
        )
    end_s, end_b = equity[-1]["strategy"], equity[-1]["benchmark"]
    r2 = _rng("t" + seed)
    trades: list[dict[str, Any]] = []
    price = 150.0
    for i in range(ntr):
        price *= 1 + (r2.random() - 0.48) * 0.06
        side = "buy" if i % 2 == 0 else "sell"
        pnl = round((r2.random() - 0.42) * 400, 2) if side == "sell" else None
        trades.append(
            {
                "id": f"tr-{i + 1}",
                "date": f"2023-{(i % 12) + 1:02d}-{(i % 21) + 1:02d}",
                "side": side,
                "price": round(price, 2),
                "qty": 1 + int(r2.random() * 10),
                "pnl": pnl,
                "returnPct": round(pnl / 1000 * 100, 2) if pnl is not None else None,
            }
        )
    wins = sum(1 for t in trades if (t["pnl"] or 0) > 0)
    r3 = _rng("m" + seed)
    monthly = [
        {
            "year": y,
            "month": m,
            "value": None if r3.random() < 0.06 else round((r3.random() - 0.44) * 10, 2),
        }
        for y in (2022, 2023)
        for m in range(1, 13)
    ]
    total_ret = round((end_s - capital) / capital * 100, 2)
    return {
        "templateId": tid,
        "asset": asset,
        "totalReturnPct": total_ret,
        "maxDrawdownPct": round(min(p["drawdown"] for p in equity), 2),
        "sharpe": round(0.4 + r.random() * 1.4, 2),
        "winRatePct": round(wins / len(trades) * 100, 1) if trades else 0.0,
        "trades": ntr,
        "vsBuyHoldPct": round((end_s - end_b) / end_b * 100, 2),
        "equity": equity,
        "monthly": monthly,
        "tradesList": trades,
        "overfitting": ntr < 30,
        "disclaimer": DISCLAIMER,
        "warnings": [{"code": "FEW_TRADES"}] if ntr < 30 else [],
        "costs": {"feePct": fee_pct, "estimatedFees": round(est_trades_cost, 2)},
    }
