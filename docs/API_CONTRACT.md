# BacktestLab API contract v1.0.0 (source of truth)

Base: `VITE_API_BASE` (default `http://localhost:8000`). All versioned paths
are prefixed `/api/v1`. Generated OpenAPI: `GET /openapi.json`; committed
snapshot: `docs/openapi.snapshot.json` (regenerate with
`python backend/scripts/update_openapi_snapshot.py`).

- Auth: `Authorization: Bearer <jwt>` (HS256, access token).
- Error envelope: `{"code", "message", "details": [], "requestId"}`.
- `X-Request-ID` is echoed on every response; a valid client value is reused,
  otherwise a 128-bit hex id is generated.
- JSON numbers are numbers (percentages as `12.5` = 12.5%). Dates/timestamps are
  UTC ISO-8601.

---

## 1. General error codes

| Code | HTTP | Meaning |
|---|---|---|
| `BAD_INPUT` | 422 | Invalid payload/parameter |
| `UNKNOWN_DATA_PROVIDER` | 422 | Unknown or disabled `dataProvider` |
| `UNKNOWN_TEMPLATE` | 422 | Unknown `templateId` |
| `UNKNOWN_ASSET` | 422 | Asset not in the API allowlist (`GET /assets`) |
| `LEVERAGE_NOT_ALLOWED` | 422 | Spot only: `leverage` must be 1, `short` false |
| `ENGINE_NOT_ALLOWED` | 422 | Vendor engine rejected the configuration |
| `ENGINE_UNAVAILABLE` | 503 | Vendor engine failed to load/run (never silently replaced) |
| `DATA_NOT_IN_STORE` | 422 | `local_store` has no coverage for the range |
| `DAILY_LIMIT_REACHED` | 429 | Daily backtest quota exhausted |
| `RATE_LIMITED` | 429 | Provider rate limit, login lockout (with `Retry-After`), etc. |
| `SERVER_BUSY` | 503 | Queue kill switch/paused |
| `PAYLOAD_TOO_LARGE` | 413 | Request body > 1,000,000 bytes |
| `UNAUTHORIZED` | 401 | Missing/invalid/expired token |
| `INVALID_CREDENTIALS` | 401 | Bad email/password |
| `INVALID_TOKEN` | 401 | Invalid/reused refresh or reset token |
| `INVALID_EMAIL` / `WEAK_PASSWORD` / `INVALID_NAME` | 422 | Registration validation |
| `EMAIL_TAKEN` | 409 | Email already registered |
| `NOT_FOUND` | 404 | Missing/foreign resource |
| `BILLING_NOT_CONFIGURED` | 501 | Checkout/portal while `BILLING_ENABLED=false` |
| `NOT_AVAILABLE` | 501 | Legacy billing alias (kept for compatibility) |
| `INTERNAL` | 500 | Unhandled server error (message redacted) |

## 2. Provider error codes (HTTP mapping)

Provider failures always name the provider; there is no silent fallback to
synthetic data. A transient failure may fall back only to a compatible real
provider (same instrument, asset class, market type, timeframe and
adjusted/unadjusted semantics), and the response provenance records the
substitution.

| Code | HTTP | Meaning |
|---|---|---|
| `UPSTREAM_BLOCKED` | 502 | Anti-bot / challenge / 403 / 429-after-retries |
| `UPSTREAM_UNAVAILABLE` | 503 | Timeout / 5xx / network down / DNS failure |
| `UPSTREAM_BAD_RESPONSE` | 502 | Unparseable / malformed body |
| `UNKNOWN_SYMBOL` | 422 | Upstream clearly says “no such symbol” |
| `PROVIDER_NOT_CONFIGURED` | 503 | Missing API key or optional package not installed |
| `RATE_LIMITED` | 429 | Explicit rate-limit signal (honor Retry-After when present) |
| `BAD_INPUT` | 422 | Caller supplied an invalid symbol/interval/range |
| `PROVIDER_NO_DATA` | 422 | Upstream returned an empty-but-valid result (never retried) |
| `EMPTY_DATA` | 422 | Legacy alias of `PROVIDER_NO_DATA` |
| `PROVIDER_COOLDOWN` | 503 | Provider parked after an anti-bot block; `Retry-After` set |
| `PROVIDER_DOWN` | 503 | Legacy catch-all (kept for back-compat) |
| `PROVIDER_TIMEOUT` | 503 | Legacy timeout alias |
| `DATA_NOT_IN_STORE` | 422 | Local store has no coverage for the requested range |

No-data responses are `422`, not `404`: the request is well-formed but the
upstream has nothing for that symbol/range. The error body is allow-listed to
`provider`, `symbol`, `start`, `end` and `retryAfter`; raw upstream payloads are
never returned. An anti-bot block parks the provider for `PROVIDER_COOLDOWN_S`
and returns `PROVIDER_COOLDOWN` (503) for the duration instead of retrying the
challenge page.

---

## 3. Endpoints

| Method | Path | Auth | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/health` | no | — | `{ok, service, time}` (liveness, no dependencies) | — |
| GET | `/api/v1/health` | no | — | `{ok:true}` (compat liveness alias) | — |
| GET | `/ready` | no | — | `{ok, db, migrations{status,current,head}, store, vendor{available,detail}}`; 503 when not ready | — |
| GET | `/metrics` | no | — | Prometheus text (`text/plain; version=0.0.4`) | — |
| GET | `/docs-contract` | no | — | `{version:"1.0.0"}` | — |
| POST | `/api/v1/auth/register` | no | `{name,email,password}` | 201 `{token,access_token,refresh_token,user}` | INVALID_EMAIL, WEAK_PASSWORD, INVALID_NAME, EMAIL_TAKEN, RATE_LIMITED |
| POST | `/api/v1/auth/login` | no | `{email,password}` | `{token,access_token,refresh_token,user}` | INVALID_CREDENTIALS, RATE_LIMITED |
| POST | `/api/v1/auth/forgot` | no | `{email}` | `{ok:true}` | RATE_LIMITED |
| POST | `/api/v1/auth/reset` | no | `{token,password}` | `{ok:true}` | INVALID_TOKEN |
| POST | `/api/v1/auth/refresh` | no | `{refresh_token}` | `{token,access_token,refresh_token}` (rotation; reuse revokes all) | INVALID_TOKEN |
| POST | `/api/v1/auth/revoke` | yes | `{refresh_token}` | `{ok:true}` | UNAUTHORIZED |
| GET | `/api/v1/auth/me` | yes | — | `User` | UNAUTHORIZED |
| PATCH | `/api/v1/auth/me` | yes | partial `{name?,language?}` | `User` | UNAUTHORIZED, NOT_FOUND |
| DELETE | `/api/v1/auth/me` | yes | — | `{ok:true}` (deletes dependants) | UNAUTHORIZED |
| GET | `/api/v1/templates` | no | — | `{items[],total}` StrategyTemplate (11) | — |
| GET | `/api/v1/assets` | no | — | `{items[],total}` Asset (API allowlist) | — |
| GET | `/api/v1/data-providers` | no | — | `{items[],default,enabled}` DataProviderInfo (below) | — |
| POST | `/api/v1/data-providers/csv-upload` | yes | `{symbol,csv}` (CSV text) | `{ok,symbol,rows,start,end,largeGaps,path}` | BAD_INPUT (422) |
| GET | `/api/v1/data-store/availability` | yes | — | `{enabled[],default,providers[{id,nameEn,nameAr,category,available,availableDetail,requiresKey,requiresKeyEnv,licenseClass}]}` | UNAUTHORIZED |
| GET | `/api/v1/data-store/coverage?limit&offset` | yes | — | `{items[],instruments[],total,limit,offset,providers[],providerCounts{},storeEnabled}` (default 100, max 500) | UNAUTHORIZED |
| GET | `/api/v1/data-store/instruments?limit&offset` | yes | — | `{items[],total,limit,offset,timeframes[],providers[],completeCoverageRows}` | UNAUTHORIZED |
| GET | `/api/v1/data-store/hash-stability?limit&offset` | yes | — | `{stable,checks[{id,instrumentId,provider,timeframe,rangeStart,rangeEnd,expected,actual,ok,rows}],partial,limit,offset}` | UNAUTHORIZED |
| GET | `/api/v1/usage` | yes | — | `{usedToday,dailyLimit,plan,periodStart}` | UNAUTHORIZED |
| GET | `/api/v1/plans` | no | — | `{items[],billingEnabled}`; each plan also has `available` | — |
| GET | `/api/v1/invoices` | yes | — | `{items[]}` | UNAUTHORIZED |
| GET | `/api/v1/notifications` | yes | — | `{items[]}` | UNAUTHORIZED |
| GET | `/api/v1/backtests?limit&offset` | yes | — | `{items[],total,limit,offset}` BacktestSummary (default 50, max 200) | UNAUTHORIZED |
| POST | `/api/v1/backtests` | yes | BacktestConfig (+ optional `dataProvider`, `interval`) | 201 BacktestResult (sync) **or** `{jobId,backtestId,status,deduped}` (async) | see §4 |
| GET | `/api/v1/backtests/{id}` | yes (owner) | — | BacktestResult | NOT_FOUND |
| DELETE | `/api/v1/backtests/{id}` | yes (owner) | — | `{ok:true}` | NOT_FOUND |
| GET | `/api/v1/compare?ids=a,b` | yes (owner) | — | `{items[],disclaimer,requested,returned,truncated}` (max 10 ids) | — |
| GET | `/api/v1/jobs/{id}` | yes (owner) | — | `{jobId,backtestId,status,progress,error}` | NOT_FOUND |
| POST | `/api/v1/jobs/{id}/cancel` | yes (owner) | — | `{jobId,status}` | NOT_FOUND |
| GET | `/api/v1/backtests/{id}/export.csv` | yes (owner) | — | CSV trades (`id,date,side,price,qty,pnl`) | NOT_FOUND |
| GET | `/api/v1/backtests/{id}/report` | yes (owner) | — | printable HTML (escaped, disclaimer) | NOT_FOUND |
| POST | `/api/v1/billing/checkout` | yes | — | 501 `BILLING_NOT_CONFIGURED` when `BILLING_ENABLED=false` (default) | — |
| POST | `/api/v1/billing/portal` | yes | — | 501 `BILLING_NOT_CONFIGURED` when `BILLING_ENABLED=false` (default) | — |
| POST | `/api/v1/billing/webhook` | no | provider event | `{ok:true,stored:true}`; 503 when billing disabled | — |
| GET | `/api/v1/help` | no | — | `{items[]}` | — |
| POST | `/api/v1/support/contact` | no | `{...}` | `{ok:true}` | — |

### Async backtests

Add `?async=true` to `POST /api/v1/backtests`, **or** send an
`Idempotency-Key` header (1–128 chars), to queue a job instead of running
synchronously:

```json
{ "jobId": "job-…", "backtestId": "bt-…", "status": "queued", "deduped": false }
```

Poll `GET /api/v1/jobs/{jobId}` until `status` is `done` or `failed`, then fetch
`GET /api/v1/backtests/{backtestId}`. Repeating the same `Idempotency-Key` for
the same user returns the existing job with `deduped:true`. Quota is consumed at
submission and refunded on terminal failure. A queued job may execute in the
API process or in the separate `worker` service (atomic claim, exactly one).

---

## 4. Backtest input validation

`POST /api/v1/backtests` validates before any provider call:

| Field | Rule |
|---|---|
| `templateId` | Must be one of the 11 template ids from `GET /templates` |
| `asset` | Must be one of the 10 `GET /assets` tickers: `AAPL`, `MSFT`, `NVDA`, `TSLA`, `AMD`, `2222.SR`, `1120.SR`, `BTC-USD`, `ETH-USD`, `SPY`. With `ENGINE_MODE=vendor` the spot-equity engine additionally rejects `BTC-USD`/`ETH-USD` (`ENGINE_NOT_ALLOWED`), leaving 8 backtestable tickers. |
| `leverage` / `short` | Spot only: `leverage` must be `1`, `short` must be false → `LEVERAGE_NOT_ALLOWED` |
| `initialCapital` | Number between 100 and 1,000,000 |
| `feePct` | Number between 0 and 5 |
| `interval` | `1D`, `1W` or `1M` (the API surface) |
| `from` / `to` | Optional as a pair. When set: `YYYY-MM-DD`, `from >= 2015-01-01`, `to < today`, `to > from`, and at least 180 days |
| `params` | Must be an object when present |
| `dataProvider` | Optional; must be enabled (unknown/disabled → `UNKNOWN_DATA_PROVIDER`) |

Provider-specific failures are mapped through the table in §2 and the code in
§1. No provider failure falls back to another provider or synthetic data.

---

## 5. Types

`User = {id,name,email,plan,language,createdAt}`.

`DataProviderInfo`:

```ts
{
  id, nameEn, nameAr, category, markets[], intervals[], assetClasses[],
  supportsAdjusted, requiresKey, requiresPackage, requiresKeyEnv,
  rateLimitPerMinute, descriptionEn, descriptionAr,
  available, availableDetail, licenseClass, enabled, isDefault,
  storeSummary?  // local_store only
}
```

`licenseClass` is provenance/UI metadata only (not a selection/billing gate).

`BacktestSummary` = the scalar backtest row fields:
`{id,userId?,name,templateId,asset,status,createdAt,totalReturnPct,maxDrawdownPct,
sharpe,winRatePct,trades,vsBuyHoldPct,dataProvider}`.

`BacktestResult` = `BacktestSummary` plus:
`{config,equity[],monthly[],tradesList[],overfitting,disclaimer,warnings[],
costs{},provenance{},engine{},resultMeta{}}`.

- `equity[] = {date,strategy,benchmark,drawdown}`.
- `tradesList[] = {id,date,side,price,qty,pnl,returnPct}`.
- `resultMeta = {equityTotalPoints,equityReturned,equityDownsampled,
  tradesTotal,tradesReturned,tradesTruncated}`. API responses bound equity to
  `API_MAX_EQUITY_POINTS` (1000) and trades to `API_MAX_TRADE_ROWS` (500,
  newest kept); the stored result and CSV export remain complete.
- `engine = {mode:"vendor"|"local", engineName, vendorCommit,
  vendorVersionOrRef}`. With `ENGINE_MODE=vendor`, a vendor failure returns
  `503 ENGINE_UNAVAILABLE` (never a silent fallback).

### Provenance

The API/provider path returns:

```json
{
  "provider": "yfinance", "requested_provider": "yfinance",
  "symbol": "AAPL", "requested_symbol": "AAPL",
  "asset_class": "equity", "market_type": null, "exchange": "NASDAQ",
  "base_currency": null, "quote_currency": "USD",
  "interval": "1D",
  "requested_start": "2022-01-01", "requested_end": "2023-12-31",
  "start": "2022-01-03", "end": "2023-12-29",
  "bars": 503, "rows": 503, "dataHash": "<64 lowercase hex>",
  "timezone": "UTC", "adjusted": true, "price_adjustment": "adjusted",
  "license_class": "public_free",
  "fallback": false, "fallback_from": null, "fallback_reason": null,
  "retrieved_at": "2026-11-04T...Z", "fetched_at": "2026-11-04T...Z",
  "cache": "hit|miss", "cacheDir": "/tmp/btlab_cache"
}
```

`requested_symbol` preserves the caller's spelling (for example `BTC/USDT`)
while `symbol` is the canonical stored instrument (`BTC-USDT`). On a
compatible fallback, `provider` names the provider that served the data and
`requested_provider` / `fallback_from` name the failed primary.

The CLI/service path (`MarketDataService`) additionally exposes
`retrieval: "live"|"store"|"partial"`, `timeframe`, `data_hash` (store canonical
hash) and `warnings[]`. See
[`DATA_STORE.md`](DATA_STORE.md#5-canonical-hashes) for the two hash
definitions. `dataHash` is always 64 lowercase hex SHA-256.

---

## 6. Limits and pagination

- Free plan: 3 backtests/UTC day; pro: 100 (`DAILY_LIMIT_REACHED`, 429).
- `GET /api/v1/backtests`: default 50, max 200.
- Data-store endpoints: default 100, max 500.
- `GET /api/v1/compare`: at most 10 ids (`truncated:true` if more requested).
- Request body guard: 1,000,000 bytes (`PAYLOAD_TOO_LARGE`, 413).
- CSV upload: 5 MiB, `MAX_UPLOAD_ROWS` (default 5000) rows.
- Register: `LOGIN_MAX_PER_MIN` (default 20) attempts/min per key.
- Login lockout (DB-shared): 5 failures per account / 15 min
  (`LOGIN_MAX_ACCOUNT_FAILURES`, `LOGIN_FAILURE_WINDOW_S`) and 20 per client IP
  (`LOGIN_MAX_IP_FAILURES`); locked attempts return 429 with `Retry-After`.
- Spot only: leverage forced to 1; `LEVERAGE_NOT_ALLOWED` otherwise.
