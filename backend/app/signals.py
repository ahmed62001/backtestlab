"""Signal builders (OUR template logic) + frame loader for the vendor engine.

Signals are generated over the full loaded panel; the vendor's own _align()
shifts them by 1 bar (next-bar-open), so no look-ahead by construction.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def signal_series(template_id: str, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    c = df["close"]
    p = params or {}
    if template_id == "ma-crossover":
        f = int(p.get("fastPeriod", 20))
        s = int(p.get("slowPeriod", 50))
        fa, sa = c.rolling(f).mean(), c.rolling(s).mean()
        # Spot-only / long-only: 1 when fast > slow, 0 otherwise. Never -1.
        sig = (fa > sa).astype(float).fillna(0.0)
        sig.iloc[:s] = 0.0
        return sig
    if template_id == "rsi":
        n = int(p.get("rsiPeriod", 14))
        lo = float(p.get("oversold", 30))
        hi = float(p.get("overbought", 70))
        d = c.diff()
        gains, losses = d.clip(lower=0), (-d).clip(lower=0)
        ag = gains.ewm(alpha=1 / n, adjust=False).mean()
        al = losses.ewm(alpha=1 / n, adjust=False).mean()
        rsi = 100 - 100 / (1 + ag / (al + 1e-12))
        # Enter below `oversold`, exit above `overbought`; hold in between.
        state = pd.Series(float("nan"), index=c.index)
        state[rsi < lo] = 1.0
        state[rsi > hi] = 0.0
        return state.ffill().fillna(0.0)
    if template_id == "breakout":
        lb = int(p.get("lookback", 20))
        buf = float(p.get("bufferPct", 0.5)) / 100.0
        hi = c.shift(1).rolling(lb).max()
        return (c > hi * (1 + buf)).astype(float).fillna(0.0)
    if template_id == "mean-reversion":
        lb = int(p.get("lookback", 20))
        ze = float(p.get("zEntry", 2))
        zx = float(p.get("zExit", 0.5))
        m, sd = c.rolling(lb).mean(), c.rolling(lb).std()
        z = (c - m) / (sd + 1e-12)
        # Enter when z < -zEntry, exit once z has reverted above -zExit.
        state = pd.Series(float("nan"), index=c.index)
        state[z < -ze] = 1.0
        state[z > -zx] = 0.0
        return state.ffill().fillna(0.0)
    if template_id == "ema-cross":
        f = int(p.get("fastPeriod", 12))
        s = int(p.get("slowPeriod", 26))
        fa, sa = c.ewm(span=f, adjust=False).mean(), c.ewm(span=s, adjust=False).mean()
        sig = ((fa > sa).astype(float) - (fa <= sa).astype(float)).fillna(0.0)
        sig.iloc[:s] = 0.0
        return ((sig + 1) / 2).fillna(0.0)  # long-only 0/1
    if template_id == "macd":
        f = int(p.get("fastPeriod", 12))
        s = int(p.get("slowPeriod", 26))
        g = int(p.get("signalPeriod", 9))
        macd = c.ewm(span=f, adjust=False).mean() - c.ewm(span=s, adjust=False).mean()
        line = macd.ewm(span=g, adjust=False).mean()
        sig = (macd > line).astype(float).fillna(0.0)
        sig.iloc[: s + g] = 0.0
        return sig
    if template_id == "bollinger":
        lb = int(p.get("lookback", 20))
        k = float(p.get("numStd", 2))
        m, sd = c.rolling(lb).mean(), c.rolling(lb).std()
        sig = pd.Series(0.0, index=c.index)
        sig[c < (m - k * sd)] = 1.0
        return sig.fillna(0.0)
    if template_id in ("donchian", "breakout"):
        lb = int(p.get("lookback", 20))
        buf = float(p.get("bufferPct", 0.0)) / 100.0
        hi = c.shift(1).rolling(lb).max()
        return (c > hi * (1 + buf)).astype(float).fillna(0.0)
    if template_id == "dca":
        n = max(1, int(p.get("frequencyDays", 30)))
        # Periodic contributions modelled as a long-only exposure ramp: a
        # contribution every `frequencyDays` bars, each worth 1/steps of the
        # target allocation. `frequencyDays` therefore changes the strategy
        # shape instead of being an ignored setting (D-PH6-04).
        steps = max(1, (len(c) + n - 1) // n)
        inc = 1.0 / steps
        sig = pd.Series(0.0, index=c.index)
        for k in range(steps):
            idx = k * n
            if idx >= len(c):
                break
            sig.iloc[idx:] = sig.iloc[idx:] + inc
        return sig.clip(upper=1.0)
    if template_id == "momentum":
        lb = int(p.get("lookback", 60))
        roc = c / c.shift(lb) - 1
        sig = (roc > 0).astype(float).fillna(0.0)
        sig.iloc[:lb] = 0.0
        return sig
    # buy-hold / default: fully invested from the first executable bar. No
    # artificial warm-up delay (D-PH6-06).
    return pd.Series(1.0, index=c.index)


class FrameLoader:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def fetch(self, codes, start, end, fields=None, interval="1D"):
        out = {}
        for code in codes:
            df = self._frame
            if start:
                df = df[df.index >= pd.Timestamp(start)]
            if end:
                end_s = str(end).strip()
                end_ts = pd.Timestamp(end_s)
                # Date-only upper bound must include all intraday bars on that day.
                if len(end_s) == 10 and "T" not in end_s and " " not in end_s:
                    end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
                df = df[df.index <= end_ts]
            out[code] = df
        return out


class TemplateSignals:
    def __init__(self, template_id: str, params: dict[str, Any]):
        self._tid = template_id
        self._params = params or {}

    def generate(self, data_map):
        # Hard long-only clamp at the signal boundary (D-PH6-01): a template
        # bug can never send a negative (short) or >1 (margin) target.
        return {
            k: signal_series(self._tid, df, self._params).clip(lower=0.0, upper=1.0).fillna(0.0)
            for k, df in data_map.items()
        }
