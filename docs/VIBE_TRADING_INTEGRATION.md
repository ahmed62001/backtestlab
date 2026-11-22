# Vibe-Trading integration (REAL, in-process) — 2026-10-18

Vendor: backend/vendor/Vibe-Trading @ c546e877274e7d36056c042808e1a875d9081eb9
(shallow main clone). License: MIT (backend/vendor/Vibe-Trading/LICENSE,
first line "MIT License", (c) 2026 Vibe-Trading Contributors). Pinned in
THIRD_PARTY_NOTICES.md. No AGPL. No LLM in run path.

## Call graph (exact paths, signatures)
- agent/backtest/engines/base.py:891
  BaseEngine.run_backtest(self, config, loader, signal_engine, run_dir,
  bars_per_year=252) -> Dict. Pipeline: loader.fetch() ->
  signal_engine.generate() -> _align() next-bar shift(1) (base.py:341) ->
  _execute_bars() -> calc_metrics() -> artifacts.
- agent/backtest/engines/global_equity.py:60 class GlobalEquityEngine(BaseEngine)
  = US/HK/CA/UK SPOT equities. CHOSEN engine. Leverage forced 1.0 by adapter.
- agent/backtest/engines/crypto.py:43 class CryptoEngine(BaseEngine) =
  crypto PERPETUALS (funding 8h, liquidation, margin). NOT used; adapter
  rejects any crypto asset at the boundary (denylist test proves it).
- agent/backtest/metrics.py:557 calc_metrics(equity_curve, trades,
  initial_cash, bars_per_year=252, ...) — reused verbatim via engine run.
- agent/backtest/loaders/local_loader.py:275 LocalLoader.fetch() — file
  loader; we use our own FrameLoader with the same fetch() duck-type.
- agent/backtest/runner.py (python -m backtest.runner <run_dir>, config.json +
  signal_engine.py sandbox) — NOT used; file+AST overhead buys nothing.

## Strategy decision
(A) in-process library call — CHOSEN. Evidence:
docs/evidence/vendor_smoke.json (GlobalEquityEngine in-process, final_value
10543.70, 5 trades, sharpe 0.764 on 120 seeded bars).
(B) subprocess (generated signal_engine.py, temp dir, timeout+mem cap) —
REJECTED: boot+IPC overhead, weaker timeout control, no benefit.
(C) local HTTP vibe-trading serve — REJECTED: no serve entry in tree
(agent/api_server.py is an agent API, not a backtest server).

## Allowlist/denylist (backend/app/adapter.py::_reject_if_banned)
Allow: AAPL MSFT NVDA TSLA AMD SPY 2222.SR 1120.SR (spot equity).
Deny: leverage!=1, short, margin, futures/perpetual/options words, crypto
hints (BTC/ETH/-USD/PERP/FUT/OPT). Violation -> EngineRejectedError -> 422.

## Invocation (backend/app/adapter.py::VibeTradingEngine.run)
vcfg = {codes:[asset], start_date, end_date, interval 1D, initial_cash,
leverage 1.0, us_commission fee/2, slippage_us fee/2}
eng = GlobalEquityEngine(vcfg)
raw = eng.run_backtest(vcfg, FrameLoader(bars), TemplateSignals(tid,params),
Path(tempdir)); then pipeline.normalize() maps raw to API contract.

