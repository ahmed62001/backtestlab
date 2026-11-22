# ENGINE VERIFICATION — vendor engine is really used at runtime (2026-10-19)

## 1. Vendor license + pinned commit (verified this run)

```
$ head -3 backend/vendor/Vibe-Trading/LICENSE
MIT License
Copyright (c) 2026 Vibe-Trading Contributors

$ cat backend/vendor/VIBE_TRADING_VERSION   # upstream license text snapshot
# pinned commit is recorded in backend/vendor/README.md,
# backend/app/adapter.py::VENDOR_COMMIT and THIRD_PARTY_NOTICES.md:
c546e877274e7d36056c042808e1a875d9081eb9
```

- The vendor tree is committed as **regular files** (no nested `.git`, no
  submodule); the pinned commit above was captured from the upstream clone at
  vendoring time. See `backend/vendor/README.md` for origin and update steps.

- License type: **MIT** (permissive; no AGPL/copyleft contagion). Pinned in
  `THIRD_PARTY_NOTICES.md`. `vendor/` is never edited by us.
- `pip-audit` / AGPL grep: no AGPL dependency anywhere in `backend/requirements.txt`.

## 2. Real call path: POST /api/v1/backtests → vendor code

| Hop | File:function | What happens |
|---|---|---|
| 1 | `backend/app/main.py:create_bt` (route `POST /api/v1/backtests`) | auth, template/leverage validation, daily limit |
| 2 | `backend/app/main.py:create_bt` → `app.data.get_provider(...).fetch(...)` | OHLCV bars (Phase 2: per-provider `fetch_ohlcv`) |
| 3 | `backend/app/adapter.py:VibeTradingEngine.run` | allow/deny list (spot-only, long-only, leverage=1), builds vendor config |
| 4 | `backend/app/adapter.py:load_vendor_engine` | lazy import `backtest.engines.global_equity.GlobalEquityEngine` from `backend/vendor/Vibe-Trading/agent` |
| 5 | `backend/app/signals.py:FrameLoader.fetch` + `TemplateSignals.generate` | our loader/signal duck-types satisfy the vendor loader/signal interfaces |
| 6 | **vendor** `agent/backtest/engines/global_equity.py:GlobalEquityEngine` → **vendor** `agent/backtest/engines/base.py:891 BaseEngine.run_backtest` | loader.fetch → signal_engine.generate → `_align()` (base.py:245) shifts signals 1 bar (base.py:341, next-bar-open) → `_execute_bars()` (base.py:1207) → `metrics.calc_metrics` |
| 7 | `backend/app/pipeline.py:normalize` | vendor engine `equity_snapshots`/`trades` + raw metrics → API contract result + `engine` block |

## 3. No silent fallback (enforced + tested)

- `ENGINE_MODE` ∈ {`vendor`, `local`} only; anything else (incl. legacy `test`)
  refuses boot (`app/engine.py`). `ENV=production` + `ENGINE_MODE!=vendor` →
  REFUSE_BOOT.
- With `ENGINE_MODE=vendor`, the vendor import is lazy
  (`adapter.load_vendor_engine`); if it fails the request returns
  **503 ENGINE_UNAVAILABLE** naming the vendor path — the local imitation is
  never executed (test: `test_vendor_failure_fails_request_no_silent_fallback`).
- The local synthetic engine runs **only** with explicit `ENGINE_MODE=local`
  (test: `test_local_mode_runs_synthetic_only_when_explicit`).

## 4. Spy proof — the vendor entry point is called

`backend/tests/test_phase1_runtime.py::test_vendor_entry_point_is_actually_called`
patches `backtest.engines.global_equity.GlobalEquityEngine.run_backtest` with a
counting subclass and asserts exactly **1** real call per API request, plus the
`engine` block `{mode: vendor, engineName: vibe-trading:GlobalEquityEngine,
vendorCommit: c546e877274e7d36056c042808e1a875d9081eb9}`.

## 5. Manual comparison table — vendor direct vs our API (run this session)

Config: `ma-crossover`, AAPL, 2022-01-01..2022-12-31, capital 10000, fee 0.1%,
params `{fastPeriod:10, slowPeriod:30}`, data = `backend/tests/golden/golden_bars.csv`.


Exact commands used (from `backend/`):

```bash
rm -f /tmp/bt_verif.db
DATABASE_URL=sqlite:////tmp/bt_verif.db DATA_PROVIDER_DEFAULT=local \
DATA_CACHE_DIR=/tmp/btlab_verifcache python3 - <<'PY'
import json, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'vendor/Vibe-Trading/agent')
import pandas as pd
from app.adapter import VibeTradingEngine
from fastapi.testclient import TestClient
from app.main import create_app
cfg = {"templateId": "ma-crossover", "asset": "AAPL", "from": "2022-01-01",
       "to": "2022-12-31", "initialCapital": 10000, "feePct": 0.1,
       "params": {"fastPeriod": 10, "slowPeriod": 30}}
df = pd.read_csv('tests/golden/golden_bars.csv', index_col=0, parse_dates=True)
raw, eng = VibeTradingEngine().run(dict(cfg), df)
print("VENDOR_DIRECT", raw["total_return"], raw["max_drawdown"],
      raw["trade_count"], raw["sharpe"])
c = TestClient(create_app(), raise_server_exceptions=False)
r = c.post('/api/v1/auth/register', json={'name':'Verify',
           'email':'verify@t.com','password':'password123'})
h = {'Authorization': 'Bearer ' + r.json()['token']}
api = c.post('/api/v1/backtests', json=cfg, headers=h).json()
print("OUR_API", api["totalReturnPct"], api["maxDrawdownPct"],
      api["trades"], api["sharpe"], api["engine"])
PY
```

Output (2026-10-19):
`VENDOR_DIRECT 0.009116813017381764 -0.0757045208282368 5 0.17719232535918797`
`OUR_API 0.91 -7.57 5 0.18 {'mode': 'vendor', 'engineName': 'vibe-trading:GlobalEquityEngine', 'vendorCommit': 'c546e877274e7d36056c042808e1a875d9081eb9', ...}`

Automated equivalent (CI): `pytest tests/test_phase1_runtime.py::test_golden_api_matches_vendor_direct -q`
— golden fixtures in `backend/tests/golden/` (`golden_bars.csv`, `api_golden.json`,
tolerance 0.011 absolute on 2-dp metrics; strict 1e-9 parity proven separately in
`tests/test_phase1.py::test_golden_vendor_vs_adapter_match`).

## 6. Look-ahead bias proof

- `test_lookahead_signal_causality`: for ma-crossover / breakout / rsi /
  momentum, the signal at bar `t` computed on truncated data `df[:t+1]` equals
  the signal on the full series → signal at `t` uses only data ≤ `t`.
- `test_lookahead_execution_is_next_bar`: the vendor's own `_align()`
  (base.py:245) output position at bar `t` equals the (clipped) signal at
  `t-1`, and bar 0 is flat → execution is strictly next-bar.

## 7. Template coverage — vendor-backed vs NOT VENDOR-BACKED

`test_all_templates_are_vendor_backed` runs **all 11** shipped templates
(ma-crossover, rsi, breakout, mean-reversion, buy-hold, ema-cross, macd,
bollinger, donchian, dca, momentum) through the real vendor engine on the AAPL
fixture. Result at this commit: **11/11 vendor-backed, 0 NOT VENDOR-BACKED.**

Notes / caveats (honesty):
- The *signal generation* is ours (`app/signals.py`); the vendor engine executes
  the signals (alignment, next-bar execution, costs, metrics). A template would
  be "NOT VENDOR-BACKED" only if it could not run through the vendor engine at
  all — none currently qualify.
- `dca` maps to a hold-mode target (periodic buys are sizing, not signal) — it
  runs on the vendor engine but does not model discrete installment purchases.
- Crypto assets and the vendor `CryptoEngine` (perpetuals) remain rejected at
  the adapter boundary (spot-only product rule); the ccxt data provider may
  still supply crypto *prices*, but the adapter allowlist keeps the engine
  spot-equity-only.

| Metric | Vendor direct (`VibeTradingEngine().run`) | Our API (`POST /api/v1/backtests`) | Match |
|---|---|---|---|
| Total return % | 0.91 | 0.91 | ✅ |
| Max drawdown % | -7.57 | -7.57 | ✅ |
| Trades | 5 | 5 | ✅ |
| Sharpe | 0.18 | 0.18 | ✅ |
| Final value | 10091.17 | (equity curve end = 10091.17) | ✅ |
