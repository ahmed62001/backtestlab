# Changelog

All notable changes for the public release `20261117T010400Z`.

## [Unreleased] — comprehensive engineering remediation

### Added / Fixed
- **Backtesting engine accuracy (`SpotBacktestEngine`)**: Replaced hardcoded US/1D `GlobalEquityEngine` assumptions with explicit `MarketProfile` resolution (US, UK, CA, HK, Saudi Tadawul, Crypto spot, FX spot, Commodity proxy), interval-aware annualisation (`1m`–`1M`), intraday `FrameLoader` end-date fix, explicit `commissionPct` / `slippagePct` / `spreadPct` cost accounting (fixing silent drop of US commission), and independent metrics (`CAGR`, `volatility`, `Sortino`, `Profit Factor`, `Expectancy`).
- **Advanced strategy controls & OOS validation**: Added Stop Loss (`none`, `fixed_pct`, `risk_based` with conservative SL-first intrabar ordering), Take Profit, Position Sizing (`pct_equity`, `fixed_amount`, `risk_based`), and chronological Out-of-Sample split evaluation across backend, wizard UI, and results view.
- **Async queue & Redis shared state**: Production async default (`ASYNC_BACKTESTS_DEFAULT=1`, `QUEUE_INPROCESS_WORKER=0` for external worker containers), Redis-backed single-use WebSocket tickets (`GETDEL`) and distributed rate limiting (`redis_store.py`), and `redis:7-alpine` in `docker-compose.yml`.
- **Security & authentication**: HttpOnly `btlab_access`/`btlab_refresh` cookies + double-submit `X-CSRF-Token` (`btlab_csrf`), removed `localStorage` JWT persistence in real mode, eliminated `'unsafe-inline'` from `script-src` CSP via `public/theme-init.js`, and removed dead `supabase_auth.py`.
- **Product & operations**: Configurable email password recovery (`email_service.py`), FRED Macro Explorer (`/app/macro`), Stripe billing abstraction (`billing.py`, disabled by default via `BILLING_ENABLED=false`, migration `d4e8f2a1c3b5`), Caddy TLS overlay (`Caddyfile`, `docker-compose.prod.yml`), PostgreSQL backup/restore verification scripts (`scripts/ops/`), and local load test (`scripts/perf/load_test.py`).

## [Unreleased] — final release hardening

### Fixed

- **Protected 1D charts / chart readiness.** Added a single-source-of-truth
  chart transform (`src/lib/chartData.ts`), the `data-*` readiness contract on
  price and comparison charts, UTC/interval-aware axis labels, and a stale
  response guard (abort + request id) in `useMarketSeries`. A slow response for
  the previously selected symbol can no longer overwrite the new selection.
- **Comparison chart truncation.** `Compare.tsx` sliced both equity curves to
  150 points (ending in June 2025). Removed; both complete curves are aligned on
  the union of timestamps with true `null` gaps (`CompareEquityChart`).
- **Intraday timestamps were not UTC.** The vendored yfinance loader strips the
  exchange timezone; intraday bars were served as if New York wall clock were
  UTC. Exchange zone is now restored for verified providers and converted to
  UTC; ambiguous DST hours are dropped rather than guessed.
- **Cache age was untruthful.** A cache hit reported `fetched_at = now`. The
  real cache write time is now reported as `fetched_at`, with
  `cache_age_s`/`served_from_cache`.
- **Freshness contract.** `/api/v1/market/series` now returns
  `freshness` (`data_status`, `is_stale`, last/last-completed candle, session,
  cache age). Session calendars cover US equities (holidays, early closes),
  crypto 24/7, CME futures (daily break/weekend) and FX 24/5.
- **WebSocket-disconnect 500s.** Replaced two `BaseHTTPMiddleware` wrappers with
  a pure-ASGI `RequestContextMiddleware`. Client disconnects no longer produce
  `RuntimeError: No response returned.` / HTTP 500; genuine errors still return
  500 and are logged.
- **Public market hardening.** Symbol length/charset validation before cache
  keys/logs, trusted-proxy-aware rate-limit key, `Cache-Control` on successful
  public series, and an explicit `BAD_SYMBOL` error.
- **Landing mobile overflow.** The hero grid could exceed the viewport for long
  symbol labels (BTC-USD); added `min-w-0` and shrinkable selects.
- **Lint.** Scoped `jsx-a11y/no-noninteractive-tabindex` suppression on the
  keyboard-focusable scroll region (`TableShell`).
- **Worker/validation robustness.** Replaced `assert`-based validation in the
  provider retry loop and upload cleanup with explicit handling; validated the
  Supabase JWKS URL scheme.
- **Warnings.** 156 backend warnings → **1** third-party warning
  (`StarletteDeprecationWarning` from `fastapi.testclient`). The dev JWT default
  is now 32+ bytes, and two test-only warnings were fixed at the source.

### Changed

- `results.retrievalLive` label changed from “Live” to “Fetched from provider”
  (English) / “جُلب من المزوّد” (Arabic) to avoid implying real-time data.
- Production boot additionally refuses well-known example JWT secrets (not just
  short ones).
- Provider cache key schema bumped to `v2` so pre-fix intraday frames are no
  longer addressed (nothing is deleted).

### Dependencies

| Package | Old | New | Reason | Covered by |
|---|---|---|---|---|
| `requests` | 2.32.5 | 2.33.0 | `PYSEC-2026-2275` (`extract_zipped_paths` predictable temp file) | full backend suite (361 passed) + `pip-audit` (0 findings) |

No other dependency was added, removed or upgraded.

### Tests added

- Backend: `test_market_sessions.py`, `test_intraday_timezone.py`,
  `test_cache_provenance.py`, `test_phase4_disconnect.py`,
  `test_public_market_security.py`, plus freshness/isolation cases in existing
  files.
- Frontend: `chartData.test.ts`, stale-response cases in `useMarket.test.tsx`.
- Harnesses: `scripts/release/{chartReady,verify-charts,verify-chart-behaviour,
  visual-qa,soak_ws,e2e-real-user,phase2_verify,phase3_provider_diff,
  recompute_metrics,secret_scan}.*`.
