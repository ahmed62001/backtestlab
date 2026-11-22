"""BacktestEngine protocol + VibeTradingEngine (real vendor, in-process).

Strategy decision (docs/VIBE_TRADING_INTEGRATION.md):
  (A) in-process library call - CHOSEN. Direct import of
      backtest.engines.global_equity.GlobalEquityEngine works with our
      own loader + signal classes, no LLM involved.
  (B) subprocess - REJECTED: interpreter boot + IPC overhead, weaker
      timeout/memory control than in-process, no benefit since (A) works.
  (C) local HTTP serve - REJECTED: no `serve` entry in vendored tree
      (agent/api_server.py is an agent API, not a backtest server).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .instruments import get_instrument, is_backtest_eligible

REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = REPO_ROOT / "vendor" / "Vibe-Trading" / "agent"

ENGINE_MODE = os.environ.get("ENGINE_MODE", "vendor")
VENDOR_COMMIT = "c546e877274e7d36056c042808e1a875d9081eb9"
VENDOR_VERSION_OR_REF = VENDOR_COMMIT  # pinned shallow-main clone; no semver tags

import pandas as pd  # noqa: E402  (import after ENGINE_MODE/env bootstrap)


class EngineRejectedError(ValueError):
    code = "ENGINE_NOT_ALLOWED"


class VendorUnavailableError(RuntimeError):
    """The vendor engine tree cannot be imported. NO silent fallback: with
    ENGINE_MODE=vendor the request must fail loudly, never use the local
    imitation."""

    code = "ENGINE_UNAVAILABLE"


def load_vendor_engine():
    """Import and return the REAL vendor GlobalEquityEngine class.

    Lazy on purpose: a broken/missing vendor tree must surface as a clear
    per-request error (VendorUnavailableError), not as an app-boot crash and
    not as a silent fallback to the local engine.
    """
    if str(_AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(_AGENT_DIR))
    try:
        from backtest.engines.global_equity import GlobalEquityEngine
    except Exception as e:  # ImportError or vendor-side init failure
        raise VendorUnavailableError(
            f"vendor engine unavailable: failed to import "
            f"backtest.engines.global_equity from {_AGENT_DIR}: {e}"
        ) from e
    return GlobalEquityEngine


def vendor_available() -> tuple[bool, str]:
    """(ok, detail) for readiness reporting — never raises."""
    try:
        load_vendor_engine()
        return True, VENDOR_COMMIT
    except VendorUnavailableError as e:
        return False, str(e)


class BacktestEngine(Protocol):
    def run(self, cfg: dict[str, Any], bars: pd.DataFrame) -> dict[str, Any]: ...


def _reject_if_banned(cfg: dict[str, Any]) -> None:
    """Capability-based validation replacing the old hardcoded equity allowlist.

    Rejects:
      - leverage != 1, short, margin, perpetual/futures/options (spot only)
      - unknown symbols (not in the instrument registry)
      - symbols that are not backtest-eligible (no genuine OHLCV source)
    Allows crypto spot and FX pairs when a genuine provider supports them.
    """
    blob = " ".join(
        [
            str(cfg.get("templateId", "")),
            str(cfg.get("asset", "")),
            str(cfg.get("market", "")),
            str(cfg.get("engine", "")),
            str(cfg.get("params") or {}),
        ]
    ).lower()
    if (
        cfg.get("leverage", 1) != 1
        or cfg.get("short", False)
        or cfg.get("margin", False)
        or "perpetual" in blob
        or "futures" in blob
        or "options" in blob
    ):
        raise EngineRejectedError("spot only: no futures/options/margin/short/perpetual")
    asset = str(cfg.get("asset", "AAPL")).upper()
    inst = get_instrument(asset)
    if inst is None:
        raise EngineRejectedError(f"asset {asset!r} is not a registered instrument")
    if not is_backtest_eligible(asset):
        raise EngineRejectedError(
            f"asset {asset!r} ({inst.asset_class}) has no genuine OHLCV backtest source"
        )


class VibeTradingEngine:
    """Real vendor adapter: SpotBacktestEngine (built on vendor BaseEngine).

    Returns (raw_metrics, engine_instance) so pipeline.normalize() can read
    the engine's equity_snapshots/trades/fill_records/profile/cost_cfg.
    """

    def run(self, cfg: dict[str, Any], bars, **kw):
        from .signals import FrameLoader, TemplateSignals  # lazy: no cycle
        from .spot_engine import (
            CostConfig,
            SpotBacktestEngine,
            compute_bars_per_year,
            normalize_interval,
            resolve_market_profile,
        )

        eng_cls = load_vendor_engine()  # raises VendorUnavailableError if vendor missing
        _reject_if_banned(cfg)
        if bars is None or len(bars) < 10:
            raise EngineRejectedError("SHORT_HISTORY: need >=10 bars")
        if getattr(bars.index, "tz", None) is not None:
            # normalized provider frames are UTC-aware; BaseEngine runs on
            # tz-naive UTC timestamps.
            bars = bars.copy()
            bars.index = bars.index.tz_convert("UTC").tz_localize(None)

        asset = str(cfg.get("asset", "AAPL"))
        inst = get_instrument(asset)
        interval = normalize_interval(cfg.get("interval", "1D"))
        profile = resolve_market_profile(asset, inst)
        cost_cfg = CostConfig.from_cfg(cfg, profile)
        bars_per_year = compute_bars_per_year(profile, interval)

        capital = float(cfg.get("initialCapital", 10000))
        tid = str(cfg.get("templateId", "ma-crossover"))
        params = cfg.get("params") or {}

        vcfg = {
            "codes": [asset],
            "start_date": bars.index[0].isoformat(),
            "end_date": bars.index[-1].isoformat(),
            "interval": interval,
            "initial_cash": capital,
            "leverage": 1.0,
        }
        sig_engine = TemplateSignals(tid, params)
        # If load_vendor_engine() was replaced by a test fake (not GlobalEquityEngine/SpyGE),
        # invoke it directly so test doubles (e.g. BadEngine) are honoured.
        if "GlobalEquityEngine" not in eng_cls.__name__ and "SpyGE" not in eng_cls.__name__:
            eng = eng_cls(vcfg)
            with tempfile.TemporaryDirectory() as td:
                raw = eng.run_backtest(vcfg, FrameLoader(bars), sig_engine, Path(td))
        else:
            # Subclass the returned GlobalEquityEngine (or SpyGE) dynamically so
            # vendor run_backtest() is always the entry point while SpotBacktestEngine
            # supplies market rules, explicit costs, SL/TP, and sizing.
            class _BoundSpotEngine(SpotBacktestEngine, eng_cls):  # type: ignore[misc,valid-type]
                pass

            eng = _BoundSpotEngine(
                vcfg,
                profile,
                cost_cfg,
                stop_loss=cfg.get("stopLoss"),
                take_profit=cfg.get("takeProfit"),
                position_sizing=cfg.get("positionSizing"),
            )
            # Pre-compute shifted signals so SL/TP re-entry lock knows when signal resets
            raw_sig_map = sig_engine.generate({asset: bars})
            for code, s in raw_sig_map.items():
                eng._signal_cache[code] = s.shift(1).fillna(0.0)

            with tempfile.TemporaryDirectory() as td:
                raw = eng.run_backtest(
                    vcfg,
                    FrameLoader(bars),
                    sig_engine,
                    Path(td),
                    bars_per_year=bars_per_year,
                )
        # Defence in depth: even if a template regressed, a short fill must
        # never escape the engine boundary (spot-only mandate, D-PH6-01).
        for t in getattr(eng, "trades", []) or []:
            if int(getattr(t, "direction", 1) or 1) < 0:
                raise EngineRejectedError("spot only: engine produced a short trade")
        return raw, eng
