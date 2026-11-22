"""Market-aware, spot-only BacktestEngine built on Vibe-Trading's BaseEngine.

Replaces the hardcoded US-daily assumptions in GlobalEquityEngine(vcfg) with:
- Explicit MarketProfile per asset class & exchange (US, UK, CA, HK, SA/Tadawul,
  Crypto spot, FX spot, ETF/Index/Commodity spot proxy)
- Explicit, non-double-counted transaction cost model (commissionPct,
  slippagePct, spreadPct, optional statutory UK SDRT)
- Interval-aware annualisation (bars_per_year) for 1m..1M
- Conservative OHLC Stop-Loss / Take-Profit execution (gap-aware, SL-first)
- Position sizing modes (pct_equity, fixed_amount, risk_based) with spot-only
  cash and max-allocation constraints
- Independent reference metrics computation with safe edge-case handling
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np
import pandas as pd

from .adapter import EngineRejectedError, load_vendor_engine
from .instruments import Instrument, get_instrument

# Canonical interval normalization: map lowercase/uppercase aliases to one form
CANONICAL_INTERVALS: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "1H": "1H",
    "4h": "4H",
    "4H": "4H",
    "1d": "1D",
    "1D": "1D",
    "1w": "1W",
    "1W": "1W",
    "1M": "1M",
}

SUPPORTED_BACKTEST_INTERVALS: tuple[str, ...] = (
    "1m",
    "5m",
    "15m",
    "30m",
    "1H",
    "4H",
    "1D",
    "1W",
    "1M",
)

INTRADAY_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1H", "4H"})


def normalize_interval(interval: str | None) -> str:
    """Normalize an interval string to canonical form, or raise EngineRejectedError."""
    raw = (interval or "1D").strip()
    canon = CANONICAL_INTERVALS.get(raw)
    if canon is None or canon not in SUPPORTED_BACKTEST_INTERVALS:
        raise EngineRejectedError(
            f"UNSUPPORTED_INTERVAL: {raw!r} is not supported "
            f"(valid: {', '.join(SUPPORTED_BACKTEST_INTERVALS)})"
        )
    return canon


def interval_to_provider_tf(interval: str) -> str:
    """Convert canonical interval ('1H', '1D', ...) to DataProvider timeframe ('1h', '1d', ...)."""
    canon = normalize_interval(interval)
    if canon in ("1H", "4H", "1D", "1W"):
        return canon.lower()
    return canon


@dataclass(frozen=True)
class MarketProfile:
    key: str
    asset_class: str
    exchange: str
    currency: str
    trading_days_per_year: int
    session_minutes_per_day: int
    qty_precision: int  # decimal places for fractional; 0 = whole units
    board_lot: int  # >1 for HK board lots, 1 otherwise
    price_precision: int
    fractional: bool
    session_label: str


_PROFILES: dict[str, MarketProfile] = {
    "us_equity": MarketProfile(
        key="us_equity",
        asset_class="equity",
        exchange="US",
        currency="USD",
        trading_days_per_year=252,
        session_minutes_per_day=390,
        qty_precision=2,
        board_lot=1,
        price_precision=2,
        fractional=True,
        session_label="US Regular (09:30-16:00 America/New_York)",
    ),
    "uk_equity": MarketProfile(
        key="uk_equity",
        asset_class="equity",
        exchange="LSE",
        currency="GBP",
        trading_days_per_year=252,
        session_minutes_per_day=510,
        qty_precision=0,
        board_lot=1,
        price_precision=2,
        fractional=False,
        session_label="LSE (08:00-16:30 Europe/London)",
    ),
    "ca_equity": MarketProfile(
        key="ca_equity",
        asset_class="equity",
        exchange="TSX",
        currency="CAD",
        trading_days_per_year=252,
        session_minutes_per_day=390,
        qty_precision=0,
        board_lot=1,
        price_precision=2,
        fractional=False,
        session_label="TSX (09:30-16:00 America/Toronto)",
    ),
    "hk_equity": MarketProfile(
        key="hk_equity",
        asset_class="equity",
        exchange="HKEX",
        currency="HKD",
        trading_days_per_year=252,
        session_minutes_per_day=330,
        qty_precision=0,
        board_lot=100,
        price_precision=2,
        fractional=False,
        session_label="HKEX (09:30-16:00 Asia/Hong_Kong)",
    ),
    "sa_equity": MarketProfile(
        key="sa_equity",
        asset_class="equity",
        exchange="TADAWUL",
        currency="SAR",
        trading_days_per_year=250,
        session_minutes_per_day=300,
        qty_precision=0,
        board_lot=1,
        price_precision=2,
        fractional=False,
        session_label="Tadawul (10:00-15:00 Asia/Riyadh, Sun-Thu)",
    ),
    "crypto": MarketProfile(
        key="crypto",
        asset_class="crypto",
        exchange="CRYPTO_SPOT",
        currency="USD",
        trading_days_per_year=365,
        session_minutes_per_day=1440,
        qty_precision=6,
        board_lot=1,
        price_precision=4,
        fractional=True,
        session_label="24/7 Spot (UTC)",
    ),
    "fx": MarketProfile(
        key="fx",
        asset_class="fx",
        exchange="FX_SPOT",
        currency="USD",
        trading_days_per_year=260,
        session_minutes_per_day=1440,
        qty_precision=2,
        board_lot=1,
        price_precision=5,
        fractional=True,
        session_label="24x5 FX Spot (UTC)",
    ),
    "commodity": MarketProfile(
        key="commodity",
        asset_class="commodity",
        exchange="COMMODITY_SPOT_PROXY",
        currency="USD",
        trading_days_per_year=252,
        session_minutes_per_day=390,
        qty_precision=2,
        board_lot=1,
        price_precision=2,
        fractional=True,
        session_label="US Commodity Proxy",
    ),
}


def resolve_market_profile(asset: str, inst: Instrument | None = None) -> MarketProfile:
    """Resolve the explicit MarketProfile for an instrument symbol."""
    if inst is None:
        inst = get_instrument(asset)
    sym = (inst.symbol if inst else asset).upper()
    ac = inst.asset_class if inst else "equity"
    exch = str((inst.metadata or {}).get("exchange", "")).upper() if inst else ""
    cur = (inst.quote_currency or "USD") if inst else "USD"

    if ac == "crypto":
        return MarketProfile(**{**_PROFILES["crypto"].__dict__, "currency": cur})
    if ac == "fx":
        return MarketProfile(**{**_PROFILES["fx"].__dict__, "currency": cur})
    if ac == "commodity":
        return MarketProfile(**{**_PROFILES["commodity"].__dict__, "currency": cur})
    if sym.endswith(".SR") or exch == "TADAWUL" or cur == "SAR":
        return _PROFILES["sa_equity"]
    if sym.endswith(".HK") or exch == "HKEX" or cur == "HKD":
        return _PROFILES["hk_equity"]
    if sym.endswith(".L") or exch == "LSE" or cur in ("GBP", "GBp"):
        return _PROFILES["uk_equity"]
    if sym.endswith(".TO") or sym.endswith(".V") or exch in ("TSX", "TSXV") or cur == "CAD":
        return _PROFILES["ca_equity"]
    return MarketProfile(
        **{
            **_PROFILES["us_equity"].__dict__,
            "asset_class": ac,
            "exchange": exch or "US",
            "currency": cur,
        }
    )


def compute_bars_per_year(profile: MarketProfile, interval: str) -> int:
    """Return accurate annualisation bars/year for (market_profile, interval)."""
    canon = normalize_interval(interval)
    if canon == "1M":
        return 12
    if canon == "1W":
        return 52
    if canon == "1D":
        return profile.trading_days_per_year
    mins_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60, "4H": 240}
    bar_mins = mins_map[canon]
    bars_per_day = max(1.0, profile.session_minutes_per_day / bar_mins)
    return max(1, int(round(profile.trading_days_per_year * bars_per_day)))


@dataclass(frozen=True)
class CostConfig:
    commission_pct: float  # one-way % of notional (e.g. 0.05 = 5 bps)
    slippage_pct: float  # one-way % of price
    spread_pct: float  # full bid-ask spread % (half applied per side)
    uk_sdrt_pct: float  # optional UK SDRT on buy (0.0 by default unless enabled)

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any], profile: MarketProfile) -> CostConfig:
        has_comm = cfg.get("commissionPct") is not None
        has_slip = cfg.get("slippagePct") is not None
        fee_pct = float(cfg.get("feePct", 0.1) or 0.0)
        if has_comm or has_slip:
            comm = float(cfg.get("commissionPct", 0.0) or 0.0)
            slip = float(cfg.get("slippagePct", 0.0) or 0.0)
        else:
            # Backward-compat: split feePct 50/50 and actually charge BOTH halves.
            comm = fee_pct / 2.0
            slip = fee_pct / 2.0
        spread = float(cfg.get("spreadPct", 0.0) or 0.0)
        uk_sdrt = 0.5 if (profile.key == "uk_equity" and cfg.get("applyUkSdrt")) else 0.0
        return cls(
            commission_pct=max(0.0, comm),
            slippage_pct=max(0.0, slip),
            spread_pct=max(0.0, spread),
            uk_sdrt_pct=uk_sdrt,
        )


def _get_base_engine():
    # Ensure vendor path is on sys.path via load_vendor_engine()
    load_vendor_engine()
    from backtest.engines.base import BaseEngine  # type: ignore[import-not-found]

    return BaseEngine


_BaseEngineCls = _get_base_engine()


class SpotBacktestEngine(_BaseEngineCls):  # type: ignore[misc,valid-type]
    """Spot-only, long-only engine with market rules, explicit costs, SL/TP, and sizing."""

    def __init__(
        self,
        config: dict[str, Any],
        profile: MarketProfile,
        cost_cfg: CostConfig,
        *,
        stop_loss: dict[str, Any] | None = None,
        take_profit: dict[str, Any] | None = None,
        position_sizing: dict[str, Any] | None = None,
    ):
        # Force spot-only leverage=1.0
        config = {**config, "leverage": 1.0}
        super().__init__(config)
        self.profile = profile
        self.cost_cfg = cost_cfg
        self.stop_loss = stop_loss or {"mode": "none"}
        self.take_profit = take_profit or {"mode": "none"}
        self.position_sizing = position_sizing or {"mode": "pct_equity", "value": 100.0}
        self.trade_exit_reasons: list[str] = []
        self._wait_for_signal_reset: set[str] = set()
        self._signal_cache: dict[str, pd.Series] = {}

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        # Spot long-only: reject any short direction
        if direction < 0:
            return False
        return not (direction > 0 and symbol in self._wait_for_signal_reset)

    def round_size(self, raw_size: float, price: float) -> float:
        s = max(0.0, float(raw_size))
        if self.profile.board_lot > 1:
            lot = self.profile.board_lot
            return float(int(s // lot) * lot)
        if not self.profile.fractional or self.profile.qty_precision == 0:
            return float(math.floor(s))
        factor = 10 ** self.profile.qty_precision
        return math.floor(s * factor) / factor

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        notional = abs(float(size)) * abs(float(price))
        comm = notional * (self.cost_cfg.commission_pct / 100.0)
        if self.cost_cfg.uk_sdrt_pct > 0:
            trade_is_buy = direction > 0 if is_open else direction < 0
            if trade_is_buy:
                tax = Decimal(str(notional)) * Decimal(str(self.cost_cfg.uk_sdrt_pct / 100.0))
                comm += float(tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        # Both slippage and half-spread move fill price against the trader:
        # buy (direction > 0) pays higher; sell (direction < 0) receives lower.
        one_way_rate = (self.cost_cfg.slippage_pct + self.cost_cfg.spread_pct / 2.0) / 100.0
        slipped = float(price) * (1.0 + direction * one_way_rate)
        if self.profile.key == "ca_equity":
            tick = 0.005 if slipped < 0.50 else 0.01
            units = slipped / tick
            steps = math.ceil(units - 1e-12) if direction > 0 else math.floor(units + 1e-12)
            return round(steps * tick, 3 if tick == 0.005 else 2)
        return slipped

    def _calc_raw_size(self, symbol: str, target_notional: float, price: float) -> float:
        """Apply position sizing rules (pct_equity, fixed_amount, risk_based)."""
        if price <= 0:
            return 0.0
        mode = str(self.position_sizing.get("mode", "pct_equity"))
        max_alloc_pct = float(self.position_sizing.get("maxAllocationPct", 100.0) or 100.0)
        max_alloc_pct = min(max(max_alloc_pct, 1.0), 100.0)

        # Estimate total equity using capital + open positions at current price
        equity = self.capital
        for s, pos in self.positions.items():
            equity += pos.size * (price if s == symbol else pos.entry_price)
        max_notional = equity * (max_alloc_pct / 100.0)

        if mode == "fixed_amount":
            fixed_amt = float(self.position_sizing.get("value", target_notional) or 0.0)
            desired = min(max(0.0, fixed_amt), max_notional, target_notional)
        elif mode == "risk_based":
            risk_pct = float(self.position_sizing.get("value", 1.0) or 1.0)
            sl_pct = float(self.stop_loss.get("pct", 0.0) or 0.0)
            if sl_pct <= 0:
                desired = min(target_notional, max_notional)
            else:
                risk_dollars = equity * (risk_pct / 100.0)
                desired = min(risk_dollars / (sl_pct / 100.0), max_notional, target_notional)
        else:
            # pct_equity: target_notional already reflects signal_weight * equity;
            # apply value% and maxAllocationPct cap.
            val_pct = float(self.position_sizing.get("value", 100.0) or 100.0)
            desired = min(target_notional * (val_pct / 100.0), max_notional)

        # Spot-only: never exceed available cash (leave tiny buffer for commission/slippage)
        desired = min(desired, max(0.0, self.capital))
        return desired / abs(price)

    def before_rebalance_bar(
        self, ts: pd.Timestamp, data_map: dict[str, pd.DataFrame], codes: list[str]
    ) -> bool:
        # Clear SL/TP re-entry lock once the shifted signal drops to 0
        for c in list(self._wait_for_signal_reset):
            sig_s = self._signal_cache.get(c)
            if sig_s is not None and ts in sig_s.index and float(sig_s.loc[ts]) <= 1e-9:
                self._wait_for_signal_reset.discard(c)
        return False

    def after_rebalance_bar(
        self, ts: pd.Timestamp, data_map: dict[str, pd.DataFrame], codes: list[str]
    ) -> bool:
        sl_mode = str(self.stop_loss.get("mode", "none"))
        tp_mode = str(self.take_profit.get("mode", "none"))
        if sl_mode == "none" and tp_mode == "none":
            return False

        sl_pct = float(self.stop_loss.get("pct", 0.0) or 0.0) / 100.0
        tp_pct = float(self.take_profit.get("pct", 0.0) or 0.0) / 100.0

        for c in list(self.positions.keys()):
            pos = self.positions.get(c)
            df = data_map.get(c)
            if pos is None or df is None or ts not in df.index:
                continue
            bar = df.loc[ts]
            b_open = float(bar["open"])
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            entry = float(pos.entry_price)

            sl_price = entry * (1.0 - sl_pct) if (sl_mode != "none" and sl_pct > 0) else None
            tp_price = entry * (1.0 + tp_pct) if (tp_mode != "none" and tp_pct > 0) else None

            exit_px: float | None = None
            reason: str | None = None

            # 1. Gap at bar open (conservative: check SL gap first)
            if sl_price is not None and b_open <= sl_price:
                exit_px = b_open
                reason = "stop_loss_gap"
            elif tp_price is not None and b_open >= tp_price:
                exit_px = b_open
                reason = "take_profit_gap"
            else:
                # 2. Intrabar OHLC check: conservative SL-first if both touched
                sl_hit = sl_price is not None and b_low <= sl_price
                tp_hit = tp_price is not None and b_high >= tp_price
                if sl_hit:
                    exit_px = sl_price
                    reason = "stop_loss"
                elif tp_hit:
                    exit_px = tp_price
                    reason = "take_profit"

            if exit_px is not None and reason is not None:
                self._active_symbol = c
                slipped_exit = self.apply_slippage(exit_px, -pos.direction)
                prev_trades = len(self.trades)
                self._close_position(c, slipped_exit, ts, reason)
                if len(self.trades) > prev_trades:
                    while len(self.trade_exit_reasons) < len(self.trades) - 1:
                        self.trade_exit_reasons.append("signal")
                    self.trade_exit_reasons.append(reason)
                self._wait_for_signal_reset.add(c)

        return False

    def _close_position(
        self, symbol: str, exit_price: float, timestamp: pd.Timestamp, reason: str = "signal"
    ) -> None:
        prev_len = len(self.trades)
        super()._close_position(symbol, exit_price, timestamp, reason)
        if len(self.trades) > prev_len and len(self.trade_exit_reasons) < len(self.trades):
            while len(self.trade_exit_reasons) < len(self.trades) - 1:
                self.trade_exit_reasons.append("signal")
            self.trade_exit_reasons.append(reason)


def compute_independent_metrics(
    equity_values: list[float],
    timestamps: list[pd.Timestamp],
    trades: list[dict[str, Any]],
    initial_capital: float,
    bars_per_year: int,
    benchmark_values: list[float] | None = None,
) -> dict[str, Any]:
    """Independently compute and validate all portfolio & trade metrics.

    Handles edge cases cleanly: 0 trades, 1 trade, 0 volatility, constant equity.
    Never returns NaN or Inf.
    """
    if not equity_values or initial_capital <= 0:
        return {
            "totalReturnPct": 0.0,
            "annualizedReturnPct": 0.0,
            "volatilityPct": 0.0,
            "sharpe": 0.0,
            "sortino": None,
            "maxDrawdownPct": 0.0,
            "maxDrawdownDurationBars": 0,
            "winRatePct": 0.0,
            "profitFactor": None,
            "avgWin": 0.0,
            "avgLoss": 0.0,
            "expectancy": 0.0,
            "trades": 0,
            "benchmarkReturnPct": 0.0,
            "vsBuyHoldPct": 0.0,
        }

    eq = np.array(equity_values, dtype=np.float64)
    total_ret = (eq[-1] - initial_capital) / initial_capital
    n_bars = len(eq)

    # CAGR / annualized return
    if n_bars > 1 and eq[-1] > 0:
        years = max(n_bars / max(1, bars_per_year), 1.0 / max(1, bars_per_year))
        ann_ret = (eq[-1] / initial_capital) ** (1.0 / years) - 1.0
    else:
        ann_ret = 0.0

    # Bar returns
    if n_bars > 1:
        prev = eq[:-1]
        valid = prev > 0
        rets = np.zeros(n_bars - 1, dtype=np.float64)
        rets[valid] = (eq[1:][valid] - prev[valid]) / prev[valid]
    else:
        rets = np.array([], dtype=np.float64)

    if len(rets) > 1:
        std = float(np.std(rets, ddof=1))
        mean_r = float(np.mean(rets))
        vol = std * math.sqrt(bars_per_year)
        sharpe = (mean_r / std) * math.sqrt(bars_per_year) if std > 1e-12 else 0.0
        downside = rets[rets < 0]
        if len(downside) > 0:
            down_dev = float(np.sqrt(np.mean(downside**2)))
            sortino: float | None = (
                round((mean_r / down_dev) * math.sqrt(bars_per_year), 2)
                if down_dev > 1e-12
                else None
            )
        else:
            sortino = None
    else:
        vol = 0.0
        sharpe = 0.0
        sortino = None

    # Max drawdown & duration
    peaks = np.maximum.accumulate(np.maximum(eq, initial_capital))
    dds = np.where(peaks > 0, (eq - peaks) / peaks, 0.0)
    max_dd = float(np.min(dds)) if len(dds) else 0.0

    max_dur = 0
    cur_dur = 0
    for dd_val in dds:
        if dd_val < -1e-12:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0

    # Trade stats
    pnls = [float(t.get("pnl", 0.0) or 0.0) for t in trades]
    ntr = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = (len(wins) / ntr * 100.0) if ntr > 0 else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor: float | None = (
        round(gross_profit / gross_loss, 2) if gross_loss > 1e-12 else None
    )
    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    expectancy = (sum(pnls) / ntr) if ntr > 0 else 0.0

    # Benchmark return
    if benchmark_values and len(benchmark_values) >= 2 and benchmark_values[0] > 0:
        bench_ret = (benchmark_values[-1] - benchmark_values[0]) / benchmark_values[0]
    else:
        bench_ret = 0.0

    def _finite(val: float, digits: int = 2) -> float:
        return round(val, digits) if math.isfinite(val) else 0.0

    return {
        "totalReturnPct": _finite(total_ret * 100.0, 2),
        "annualizedReturnPct": _finite(ann_ret * 100.0, 2),
        "volatilityPct": _finite(vol * 100.0, 2),
        "sharpe": _finite(sharpe, 2),
        "sortino": sortino if (sortino is not None and math.isfinite(sortino)) else None,
        "maxDrawdownPct": _finite(max_dd * 100.0, 2),
        "maxDrawdownDurationBars": int(max_dur),
        "winRatePct": _finite(win_rate, 1),
        "profitFactor": profit_factor,
        "avgWin": _finite(avg_win, 2),
        "avgLoss": _finite(avg_loss, 2),
        "expectancy": _finite(expectancy, 2),
        "trades": ntr,
        "benchmarkReturnPct": _finite(bench_ret * 100.0, 2),
        "vsBuyHoldPct": _finite((total_ret - bench_ret) * 100.0, 2),
    }
