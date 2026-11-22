# Data providers — BacktestLab

## 1. Overview

BacktestLab has **15 registered historical-data providers**. Each provider is
an isolated module under `backend/app/data_providers/`, declares its own
markets, intervals, adjustment behavior, license metadata, key/package
requirements and health, and is exposed through one catalog endpoint:

```http
GET /api/v1/data-providers
```

```jsonc
{
  "items": [{
    "id": "yfinance",
    "nameEn": "Yahoo Finance (yfinance)",
    "nameAr": "ياهو فاينانس",
    "category": "equities",              // equities|crypto|fx|macro|local|synthetic|upload
    "markets": ["us_equity", "global_equity", "crypto"],
    "intervals": ["1D", "1H", "1W", "1M"],
    "assetClasses": ["equity", "etf", "index", "crypto", "fx"],
    "supportsAdjusted": true,
    "requiresKey": false,
    "requiresPackage": "yfinance",
    "requiresKeyEnv": null,
    "rateLimitPerMinute": 60,
    "descriptionEn": "Yahoo Finance daily/intraday bars (free, no key)",
    "descriptionAr": "أسعار ياهو فاينانس اليومية واللحظية (مجانية بدون مفتاح)",
    "available": true,
    "availableDetail": "",
    "licenseClass": "public_free",
    "enabled": true,
    "isDefault": true,
    "storeSummary": { /* only for local_store */ }
  }],
  "default": "yfinance",
  "enabled": ["yfinance", "ccxt", "...", "stooq"]
}
```

**No silent substitution.** Unknown or disabled ids are rejected with
`UNKNOWN_DATA_PROVIDER` (422). A selected provider that fails returns a typed
error naming it (for example `503 UPSTREAM_UNAVAILABLE` or
`502 UPSTREAM_BLOCKED`).

When `DATA_PROVIDER_FALLBACK=1` (default), a transient failure may be retried
against another **compatible real provider** — same registered instrument,
asset class, market type, timeframe and adjusted/unadjusted semantics. The
serving result's provenance records `fallback: true`,
`requested_provider`, `fallback_from`, `fallback_reason` and the actual
`provider`. Local, synthetic and upload datasets never substitute for real
market data (or vice versa), and FX is never substituted across providers
because bid/mid price basis and volume semantics differ. The engine never
substitutes synthetic bars.

Provider selection is per request via the optional `dataProvider` field on
`POST /api/v1/backtests`. When omitted, `DATA_PROVIDER_DEFAULT` is used.

> **Catalog health checks:** `GET /api/v1/data-providers` calls each provider's
> `health_check()` in parallel with a per-provider timeout
> (`PROVIDER_HEALTH_TIMEOUT_S`, default 2.0 s). For direct-HTTP providers
> (`coingecko`, `frankfurter`, `fred`, `twelvedata`, `polygon`) that is a
> lightweight upstream probe, so on an air-gapped machine a provider may report
> `available=false`. The assembled catalog is cached for
> `PROVIDER_CATALOG_TTL_S` (default 60 s) in **all** environments; the first
> request after expiry is served the stale snapshot while a single background
> thread refreshes it (stale-while-revalidate), so anonymous traffic never
> fans out to upstreams on every request. Set `PROVIDER_CATALOG_CACHE=0` to
> disable caching (tests/diagnostics only). Upstream error details are redacted
> before being returned. Availability is advisory: an explicitly selected
> provider is still attempted and fails with a named, typed error — unless it
> is inside an anti-bot cooldown (see §6).

---

## 2. Provider catalog

Registry/UI order is the order below (`backend/app/data_providers/registry.py`).
“Rate/min” is the provider's declared budget used for documentation and
UI display; actual spacing is enforced by each provider's `min_interval_s`.

| # | id | Category | Asset classes / markets | Intervals | Key env | Optional package | Adjusted | License | Rate/min | Notes / caveats |
|---|----|----------|-------------------------|-----------|---------|------------------|----------|---------|----------|-----------------|
| 1 | `yfinance` | equities | equity, etf, index, crypto, fx / us_equity, global_equity, crypto | 1D, 1H, 1W, 1M | — | `yfinance` | yes | public_free | 60 | Yahoo auto-adjusted closes. Intraday history is limited by Yahoo (roughly the last 730 days for 1H). No key. |
| 2 | `ccxt` | crypto | crypto / crypto | 1D, 1H, 4H, 1W | — | `ccxt` | no | public_free | 120 | Public spot OHLCV only (no keys, no trading). Exchange from `CCXT_EXCHANGE` (default `binance`). Canonical `BTC-USD` maps to `BTC/USDT`. |
| 3 | `alphavantage` | equities | equity, fx, crypto / us_equity | 1D | `ALPHAVANTAGE_API_KEY` | — | no | keyed_free_tier | 5 | Unadjusted daily. Placeholder keys (`demo`, `your-alphavantage-api-key`, empty) are treated as unconfigured → `available=false`. Free tier is per-key/IP limited. |
| 4 | `binance_public` | crypto | crypto / crypto | 1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M | — | `ccxt` (vendor loader) | no | public_free | 1200 | Public Binance REST via the vendored loader. Raw exchange prices. Very old intraday history may be unavailable upstream. |
| 5 | `coingecko` | crypto | crypto / crypto | 1H, 1D | — | — | no | public_free | 30 | Free API, no key. Both `1D` and `1H` call `/coins/{id}/market_chart/range` with the **requested** `from`/`to` window, so historical backtests work (no fixed 365-day lookback). OHLC is derived from close prices (open = previous close, high/low from open/close) plus volume. Tickers resolve through a 7-day cached `/coins/list`; an empty 200 raises `422 PROVIDER_NO_DATA` and is never retried. |
| 6 | `frankfurter` | fx | fx / fx | 1D | — | — | no | public_free | 60 | ECB daily reference rates via `frankfurter.dev`, business days only. OHLC are all the same rate; volume is 0. Supports common FX pairs. |
| 7 | `fred` | macro | macro / macro | 1D, 1W, 1M | `FRED_API_KEY` | — | no | public_free | 120 | US macro series (GDP, CPI, unemployment, rates, VIX, …). Pseudo-OHLC: all four prices = the observation value, volume 0. Missing observations (`"."`) are skipped. |
| 8 | `tiingo` | equities | equity / us_equity | 1D | `TIINGO_API_KEY` | — | yes | freemium | 60 | Split/dividend-adjusted US EOD. Free tier limits apply upstream. |
| 9 | `twelvedata` | equities | equity, crypto, fx / us_equity, crypto, fx | 1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M | `TWELVEDATA_API_KEY` | — | yes | freemium | 8 | Free tier: 8 requests/minute and a daily quota; the provider spaces calls by 8 s. Multi-asset. |
| 10 | `polygon` | equities | equity, crypto, fx / us_equity, crypto, fx | 1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M | `POLYGON_API_KEY` | — | yes | freemium | 5 | Free tier: 5 requests/minute; the provider spaces calls by 12 s. Aggregate bars, adjusted. |
| 11 | `csv_upload` | upload | equity, crypto / equity, crypto | 1D | — | — | unknown (depends on file) | user_supplied | — | Validated user CSV files stored under `DATA_UPLOAD_DIR`. Upload through `POST /api/v1/data-providers/csv-upload`. |
| 12 | `local` | local | equity / equity | 1D | — | — | unknown | dev_only | — | Recorded fixture CSVs in `backend/tests/fixtures/` (e.g. `AAPL.csv`). No network. Results carry `DATA_DEV_SOURCE`. |
| 13 | `local_store` | local | equity, etf, index, crypto, fx, macro, other / stored | 1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M | — | — | per stored row (`supportsAdjusted=true`) | local_store | — | Read-only view over the persistent market-data store. **Never** falls through to the network. Uncovered symbol/range → `422 DATA_NOT_IN_STORE`. `available` is true only when at least one complete coverage row exists. |
| 14 | `synthetic` | synthetic | equity / equity | 1D | — | — | no | dev_only | — | Deterministic seeded GBM (`sha256(symbol\|start\|end)`), business days only. Dev/tests only; the default only when `ENV=test`. Never a silent fallback. |
| 15 | `stooq` | equities | equity / us_equity | 1D | — | — | no | public_free | 60 | Free US end-of-day CSV. Canonical `AAPL` is sent as `AAPL.US`. Stooq challenges shared IPs aggressively, so it is registered **last**; a challenge (`502 UPSTREAM_BLOCKED`) parks it for `PROVIDER_COOLDOWN_S` (default 300 s) in the shared DB. Daily only. |

### Key and package gating

- Keyed providers (`alphavantage`, `fred`, `tiingo`, `twelvedata`, `polygon`)
  set `requiresKey=true` and `requiresKeyEnv=<VAR>`. Without a non-placeholder
  value they report `available=false` with `<VAR> not configured`, and a
  request fails with `503 PROVIDER_NOT_CONFIGURED`.
- `yfinance`, `ccxt` and `binance_public` need optional packages. Without
  them the app still boots; those providers report
  `available=false, availableDetail="package <name> not installed"`. Install
  `backend/requirements-providers.txt` to enable them.
- `licenseClass` is **provenance/UI metadata only**. It does not gate provider
  selection, request acceptance, billing or engine behavior. Non-`commercial_ok`
  data keeps the existing `DATA_DEV_SOURCE` warning.

---

## 3. Registry and environment variables

| Variable | Default | Behavior |
|---|---|---|
| `DATA_PROVIDER_DEFAULT` | `yfinance`; `synthetic` when `ENV=test` | Provider used when a request omits `dataProvider`. Compose defaults to `local`; E2E defaults to `local_store`. |
| `DATA_PROVIDERS_ENABLED` | all 15 ids | Comma allowlist of selectable ids, re-read on each call. Unknown/disabled ids → `UNKNOWN_DATA_PROVIDER`. |
| `ENV` | `dev` | Selects the default provider above and warning behavior. |
| `CCXT_EXCHANGE` | `binance` | Exchange used by `ccxt` (and the vendored loader). |
| `PROVIDER_CATALOG_TTL_S` | `60` | Catalog snapshot TTL in all environments (stale-while-revalidate). |
| `PROVIDER_CATALOG_CACHE` | `1` | Set `0` to disable catalog caching (tests/diagnostics only). |
| `PROVIDER_HEALTH_TIMEOUT_S` | `2.0` | Per-provider health-check timeout in the catalog. |
| `PROVIDER_COOLDOWN_S` | `300` | How long an anti-bot-blocked provider stays parked (DB-backed). |
| `COINGECKO_COIN_LIST_TTL_S` | `604800` | CoinGecko `/coins/list` id map cache (7 days). |
| `DATA_RETRY_MAX_WAIT_S` | `30` | Cap for one `Retry-After`/backoff sleep. |
| `ALPHAVANTAGE_API_KEY`, `FRED_API_KEY`, `TIINGO_API_KEY`, `TWELVEDATA_API_KEY`, `POLYGON_API_KEY` | empty | Provider keys; placeholders (`demo`, `changeme`, `your_*_key`) count as unset. |

Registry order determines UI order:
`yfinance, ccxt, alphavantage, binance_public, coingecko, frankfurter, fred,
tiingo, twelvedata, polygon, csv_upload, local, local_store, synthetic, stooq`
(`stooq` is last because its anti-bot challenges are shared-IP sensitive).

`GET /api/v1/data-store/availability` (auth required) returns the same catalog
in a slimmer shape, including `category`, `requiresKeyEnv` and
`licenseClass`.

---

## 4. Fetch pipeline, cache, retries and rate limits

All providers share `backend/app/data_providers/base.py`:

1. **Interval validation** — an unsupported interval fails immediately with
   `BAD_INPUT` (422); it is never silently coerced.
2. **Rate spacing** — each provider declares `min_interval_s`; a process-local
   limiter sleeps between calls (e.g. 8 s for TwelveData, 12 s for Polygon).
3. **Disk cache** — `DATA_CACHE_DIR` (default `/tmp/btlab_cache`), TTL
   `DATA_CACHE_TTL_S` (default 24 h). Cache key:
   `{provider}|{symbol}|{start}|{end}|{interval}`. This cache is separate from
   the persistent market-data store.
4. **Bounded retries** — `DATA_FETCH_RETRIES` attempts (default 3) with linear
   backoff `DATA_FETCH_BACKOFF_S` (default 0.5 s), capped by
   `DATA_RETRY_MAX_WAIT_S` (default 30 s). Permanent errors (`UNKNOWN_SYMBOL`,
   `BAD_INPUT`, `PROVIDER_NO_DATA`, `PROVIDER_NOT_CONFIGURED`) are not retried,
   so a genuine empty result fails fast instead of hammering the upstream.
   `Retry-After` headers are honored when present.
5. **Request-scoped de-duplication** — concurrent/sequential fetches for the
   same `{provider,symbol,start,end,interval}` inside one request reuse a single
   upstream call.
6. **Normalization** — UTC index, sorted, de-duplicated, numeric OHLCV,
   `MAX_BARS` cap (default 2000). Empty/malformed frames raise typed errors;
   an empty-but-valid response becomes `PROVIDER_NO_DATA` (422).
7. **Provenance** — every result carries provider, symbol, interval, range,
   row count, SHA-256 `dataHash`, timezone, adjustment flag, license class,
   `fetched_at`, `cache` (`hit`/`miss`) and `cacheDir`.

The **persistent store** is a second, longer-lived layer used by the CLI and
the `local_store` provider. Its TTL, coverage and hash rules are documented in
[`DATA_STORE.md`](DATA_STORE.md).

---

## 5. Local store, TTL, refresh and `retrieval`

There are two related paths:

- **API/backtest path (`POST /api/v1/backtests`, worker):** resolves the
  provider through the registry and calls `fetch_bars()` → provider disk cache
  (above). With `dataProvider="local_store"` the request reads the persistent
  store through `LocalStoreProvider` and touches no network.
- **Service path (`MarketDataService`):** used by the CLI
  (`ingest`, `ingest-file`, `backfill`) and available to Python callers. It is
  a read-through cache over `market_bars`/`market_coverage`:
  - full fresh coverage → `retrieval="store"` (no provider call);
  - no coverage → fetch and store → `retrieval="live"`;
  - some coverage → fetch only missing sub-ranges and merge →
    `retrieval="partial"`;
  - `refresh=True` ignores valid coverage and refetches;
  - expired coverage rows are ignored so a TTL refresh happens;
  - `local_store` is a special read-only case: it reads the store and never
    writes back or calls the network.

Provenance differs slightly by path:

```jsonc
// API provider path (registry/base fetch)
{
  "provider": "yfinance", "symbol": "AAPL", "interval": "1D",
  "start": "2022-01-03", "end": "2023-12-29",
  "bars": 503, "rows": 503, "dataHash": "<64 lowercase hex>",
  "timezone": "UTC", "adjusted": true, "license_class": "public_free",
  "fetched_at": "2026-11-04T...Z", "cache": "miss",
  "cacheDir": "/tmp/btlab_cache"
}

// MarketDataService path (CLI ingest/backfill)
{
  "provider": "yfinance", "symbol": "AAPL", "timeframe": "1D",
  "start": "2022-01-01", "end": "2023-12-31", "adjusted": false,
  "retrieval": "live",              // live | store | partial
  "data_hash": "<64 lowercase hex>", // store canonical hash
  "warnings": [], "rows": 522
}
```

`local_store` itself applies **no TTL**: it serves whatever bars/coverage exist.
TTL only decides when `MarketDataService` refetches live data. See
[`DATA_STORE.md`](DATA_STORE.md#coverage-and-ttl).

---

## 6. Error taxonomy

Provider failures always name the provider and carry a stable code. The API
maps the code to HTTP:

| Code | HTTP | Typical cause |
|---|---|---|
| `UPSTREAM_BLOCKED` | 502 | Anti-bot/challenge page, 401/403, 429 after retries |
| `UPSTREAM_UNAVAILABLE` | 503 | Timeout, DNS/connect failure, upstream 5xx |
| `UPSTREAM_BAD_RESPONSE` | 502 | Unparseable/malformed body |
| `UNKNOWN_SYMBOL` | 422 | Upstream clearly reports “no such symbol” |
| `PROVIDER_NOT_CONFIGURED` | 503 | Missing key or optional package |
| `RATE_LIMITED` | 429 | Explicit rate-limit signal (e.g. 429, quota message) |
| `BAD_INPUT` | 422 | Invalid symbol/interval/range; also unknown/disabled provider |
| `PROVIDER_NO_DATA` | 422 | Upstream returned an empty-but-valid result (e.g. CoinGecko empty 200) |
| `EMPTY_DATA` | 422 | Legacy alias of `PROVIDER_NO_DATA` (kept for compatibility) |
| `PROVIDER_COOLDOWN` | 503 | Provider is parked after an anti-bot block; `Retry-After` is set |
| `PROVIDER_DOWN` | 503 | Legacy catch-all (kept for compatibility) |
| `PROVIDER_TIMEOUT` | 503 | Legacy timeout alias |
| `DATA_NOT_IN_STORE` | 422 | `local_store` has no coverage for the range |

`classify_error()` converts arbitrary HTTP/network exceptions into these codes.
**No-data is a client-visible input problem, not a server outage**: an empty but
successful provider response is normalized to `PROVIDER_NO_DATA` and returns
`422` on `POST /api/v1/backtests` with a safe body listing provider, symbol,
start/end and `retryAfter` (no upstream payload). It is never retried.

**Cooldown:** when a provider answers with an anti-bot challenge (`UPSTREAM_BLOCKED`),
the registry parks it for `PROVIDER_COOLDOWN_S` (default 300 s) in the shared
database. During that window the catalog reports `available=false` with an
`availableDetail`/`retryAfter`, and `fetch_bars` refuses to call it
(`PROVIDER_COOLDOWN`, 503) instead of repeatedly hitting the challenge page.

Fallback is limited to compatible real providers and is always recorded in
provenance; there is no synthetic substitution. FX has no cross-provider
fallback (see [`FX_PROVIDERS.md`](FX_PROVIDERS.md)). Set
`DATA_PROVIDER_FALLBACK=0` to disable fallback entirely.

---

## 7. CSV upload

```http
POST /api/v1/data-providers/csv-upload
Authorization: Bearer <jwt>
Content-Type: application/json

{ "symbol": "AAPL", "csv": "date,open,high,low,close,volume\n2024-01-02,185.0,186.0,184.0,185.5,1000\n..." }
```

Validation before the file is accepted:

- symbol must match `^[A-Za-z0-9._-]{1,32}$`;
- body ≤ 5 MiB and ≤ `MAX_UPLOAD_ROWS` (default 5000) data rows;
- a `date` (or `trade_date`) column plus `open/high/low/close` (volume optional);
- UTC-parseable, strictly ascending dates, no duplicates;
- formula-injection prefixes (`=`, `+`, `-`, `@`) in cells are rejected;
- response reports `{ok, symbol, rows, start, end, largeGaps, path}`.

Files are written to `DATA_UPLOAD_DIR` as `<SYMBOL>.csv` and served by the
`csv_upload` provider. `largeGaps` counts gaps > 10 days.

---

## 8. Adding a new provider in 10 steps

A copy-ready skeleton lives at [`provider_template.py`](provider_template.py).

1. **Create the module** `backend/app/data_providers/<id>.py`. Subclass
   `DataProvider` for a direct HTTP implementation, or `VendorLoaderProvider`
   to reuse a vendored loader.
2. **Set identity and metadata:** `id`, `name_en`, `name_ar`, `markets`,
   `intervals`, `requires_key`, `license_class`, `adjusted`, `min_interval_s`,
   and a `Capabilities(...)` object (`category`, `asset_classes`, `timeframes`,
   `supports_adjusted`, `requires_package`, `requires_key_env`,
   `rate_limit_per_minute`, EN/AR descriptions).
3. **Implement `health_check()`** as a cheap probe. Never include a secret in
   `detail`; return `{"available": False, "detail": "<reason>"}` for missing
   keys/packages.
4. **Implement `fetch_ohlcv_raw(symbol, start, end, interval)`.** Return a
   `pandas.DataFrame` with OHLC(V) columns and a DatetimeIndex. Use
   `get_httpx_client(self.id)` and translate failures with
   `classify_error(self.id, exc)` or an explicit `ProviderError(code)`.
5. **Validate intervals explicitly.** Unsupported intervals raise
   `ProviderError(id, "BAD_INPUT", ...)`; never coerce silently.
6. **Register it** in `_ALL` in `backend/app/data_providers/registry.py` at the
   desired UI position.
7. **Add symbol mappings** to `backend/data/symbol_map.yaml` and, when it
   belongs to a tracked universe, to `backend/data/universe*.yaml`.
8. **Declare optional dependencies** in `backend/requirements-providers.txt`
   (and keep the import lazy/guarded) so the app still boots without them.
9. **Add offline tests** in `backend/tests/` using `respx` for HTTP: success,
   unconfigured, blocked, rate-limited, bad response and empty data. The test
   `conftest.py` blocks real sockets, so no live network is allowed.
10. **Document and verify:** update this file and `.env.example` if a key was
    added, run `ruff check .`, `ruff format --check .`, `mypy`,
    `pytest tests/ -q --cov=app --cov-fail-under=70`, `npm run verify`, and
    regenerate the OpenAPI snapshot if the catalog shape changed.

Do **not**: add a provider intended only as an unconditional fallback, fetch
data at import time, store secrets in code, or return synthetic bars when an
upstream fails. Fallback eligibility is decided centrally by
`_providers_compatible()`; a new provider must declare accurate capabilities,
market type and adjustment semantics before it can participate.

---

## 9. Live smoke checks

`backend/scripts/smoke_providers.py` exercises providers against live (or
dependency-gated) sources. Network providers are expected to report
`SKIPPED`/`FAIL` in air-gapped CI; that is not a release blocker, but record the
output in the release checklist. The scheduled CI job
`live-provider-smoke` runs it non-blocking when secrets are configured.
