# FX providers and eligibility — BacktestLab

**Last evidence refresh:** 2026-11-08  
**Status:** FX is **not enabled by default**. It becomes available only when an
operator configures a real, credentialed FX OHLCV provider. Frankfurter remains
reference-only and is never treated as a backtest source.

This document separates three things that are often conflated:

1. a provider exists in the registry;
2. a provider declares FX capability; and
3. a provider is **eligible and actually wired** for FX backtests in this
   deployment.

Only (3) makes an FX pair appear in `/api/v1/assets` or pass request
validation.

---

## 1. Eligibility rule (implemented)

`backend/app/instruments.py`:

- Registered FX instruments: `EURUSD`, `GBPUSD`, `USDJPY`.
- Supported timeframe in the instrument registry: `1D` only.
- Approved FX providers per instrument: `twelvedata`, `polygon`.
- `is_backtest_eligible("EURUSD")` returns true only when
  `configured_providers("EURUSD", "1D")` is non-empty. A provider counts as
  configured when it is:
  - enabled by `DATA_PROVIDERS_ENABLED`,
  - its optional package (if any) is importable, and
  - its required key env var (if any) is present and not a placeholder.
- `asset_catalog()` (served by `GET /api/v1/assets`) lists only
  backtest-eligible instruments. FX is therefore absent unless a key is set.

Observed behaviour:

```text
no-key FX eligible: False
with TWELVEDATA_API_KEY set: True ['twelvedata']
catalog FX entries: ['EURUSD', 'GBPUSD', 'USDJPY']
```

Frankfurter is **not** in any FX instrument's provider list. It supplies ECB
daily reference rates (open = high = low = close, volume = 0), which cannot
support an OHLCV intraday/daily backtest.

---

## 2. Provider classification

| Provider | Declares FX capability | Real FX OHLCV | Wired for FX in registry | Free tier | Key required | Classification |
|---|---|---|---|---|---|---|
| **Twelve Data** (`twelvedata`) | Yes | Yes, `time_series` with FX pairs | **Yes** | 8 credits/min, 800 credits/day; free plan advertises real-time and historical FX | `TWELVEDATA_API_KEY` | **Eligible real source** |
| **Polygon / Massive** (`polygon`) | Yes | Yes, forex aggregate bars (`C:` tickers) | **Yes** | Basic: 5 requests/min per asset class; free forex + 2 years of minute history advertised | `POLYGON_API_KEY` | **Eligible real source with semantic caveat** |
| **Frankfurter** (`frankfurter`) | Yes (reference rates) | No OHLCV; daily mid reference rates only | **No** | No key, no quota | — | **Reference only** |
| **Stooq** (`stooq`) | No in this adapter | US equity EOD only | No | No key | — | Not an FX source |
| **yfinance** (`yfinance`) | Capability list includes `fx` | Yahoo FX may be available, but this adapter/loader is not validated for FX | **No** | No key | — | **Deliberately excluded** |
| **Alpha Vantage** (`alphavantage`) | Capability list includes `fx` | FX endpoints are not implemented in this adapter (equity-only code path) | **No** | Key required | `ALPHAVANTAGE_API_KEY` | Unsupported in this adapter |

### Why yfinance is excluded from FX despite declaring it

`YFinanceProvider.capabilities` includes `fx`, and its `markets` tuple does not.
The vendor loader path is validated for equities and crypto only. Until FX
symbol mapping (`EURUSD=X`), timezone/session handling and price semantics are
covered by deterministic and live tests, FX is **not** advertised as available.
Declaring a capability is not the same as shipping a verified path.

---

## 3. Official evidence

### Twelve Data

- <https://twelvedata.com/pricing> — Basic plan: **$0**, **8 API credits per
  minute**, **800 per day**, includes **real-time forex market data**.
- <https://twelvedata.com/forex> — **“20+ years of historical exchange rates
  are available even with free plans.”** FAQ: the free Basic plan includes
  real-time and historical forex rates for major pairs, 800 requests/day, no
  credit card. Documents intraday, daily, weekly and monthly intervals.
- <https://twelvedata.com/docs> — `time_series` is the historical OHLC endpoint;
  forex is a supported market.
- <https://support.twelvedata.com/en/articles/5335783-trial> — Basic plan: 8 API
  credits (800/day), real-time data for US markets, forex and crypto.
- Unauthenticated probe on 2026-11-08:
  `GET https://api.twelvedata.com/time_series?symbol=EUR/USD...` returned
  **HTTP 401** (endpoint exists; key required).

### Polygon / Massive

- <https://massive.com/docs/rest/forex/overview> — forex custom aggregate bars
  (`GET /v2/aggs/ticker/{forexTicker}/range/...`), OHLC + volume, UTC.
- <https://massive.com/docs/rest/forex/aggregates/custom-bars.md> — bars are
  generated from quoted bid/ask prices rather than executed trades; empty
  intervals when no quotes occur.
- <https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis>
  — free Basic tier of each product allows **5 requests/minute**; limits are per
  asset class.
- <https://massive.com/blog/free-data-apis/> — free accounts include end-of-day
  U.S. equities, **forex**, and crypto, with **2 years of minute-level
  historical data**.
- <https://massive.com/currencies> — Currencies subscription covers forex and
  crypto; “Start free”.
- Official knowledge base: forex history starts **25 September 2009**, with
  documented gaps; forex volume repeats the quote count because forex has no
  traded volume.
- Unauthenticated probes on 2026-11-08 returned **HTTP 401** for both
  `https://api.polygon.io/.../C:EURUSD/...` and
  `https://api.massive.com/.../C:EURUSD/...` (endpoint reachable; key required).

### Frankfurter

- <https://frankfurter.dev/> — free exchange-rate API, 219 currencies, daily
  rates, historical data back to 1948, no key, no quotas (rate-limited for
  abuse). FAQ: “It isn't built for live trading”; rates are mid-market/daily.
- Therefore Frankfurter is a **reference-rate source**, not an OHLCV backtest
  source. It stays out of FX eligibility.

### Stooq

- The adapter implements Stooq US equity end-of-day only
  (`backend/app/data_providers/stooq.py`); it is not mapped for FX pairs.

---

## 4. Symbol mapping (fixed in this audit)

Canonical FX symbols are six letters without a separator (`EURUSD`). Provider
APIs require different forms:

| Provider | Canonical | Provider-native |
|---|---|---|
| Twelve Data | `EURUSD` | `EUR/USD` |
| Polygon / Massive | `EURUSD` | `C:EURUSD` |

Before this audit both adapters forwarded `EURUSD` unchanged, so a configured
key would have produced `UNKNOWN_SYMBOL` instead of bars. The mapping is now
implemented in `_twelvedata_symbol()` and `_polygon_symbol()`, with a
regression test that also pins existing crypto/equity mappings:

- `BTC-USDT` → Twelve Data `BTC/USDT`; Polygon `BTC-USD` → `X:BTCUSD`.
- `AAPL.US` → `AAPL` for both.

No live keyed request was made (no key is available in this environment); the
mapping itself is deterministic and unit-tested.

---

## 5. Fallback policy for FX

FX has **no cross-provider fallback**, even when both providers are configured.
`_providers_compatible()` returns `False` for any FX substitution because:

- Polygon forex bars are **bid-based** quote aggregates; other vendors may
  publish mid or bid/ask-derived series.
- Polygon `volume` repeats the quote count (forex has no traded volume), while
  other vendors may publish tick volume or zero.
- A fallback would therefore change the information set without changing the
  result's visible symbol.

The primary provider's failure is returned with its original typed error. This
is stricter than the compatibility rule for equities/crypto and is intentional.

---

## 6. How to enable FX (operator procedure)

```bash
# 1. Obtain a free key from the provider (do not commit it).
export TWELVEDATA_API_KEY="..."     # or POLYGON_API_KEY
# Optional: keep the provider enabled (default is all).
export DATA_PROVIDERS_ENABLED="twelvedata,polygon,yfinance,stooq,ccxt,..."
# Optional: require the selected provider (disable compatibility fallback).
export DATA_PROVIDER_FALLBACK=0
```

Then verify:

```bash
# FX should now appear in the catalog.
curl -s http://localhost:8000/api/v1/assets | jq '.items[] | select(.assetClass=="fx")'

# Catalog should mark the provider available.
curl -s http://localhost:8000/api/v1/data-providers | jq '.items[] | select(.id=="twelvedata")'

# Keyed live check (requires a real key; not run in CI).
python scripts/smoke_providers.py twelvedata polygon
```

If the key is missing or a placeholder, FX disappears from `/api/v1/assets`
and a direct FX backtest request is rejected with `BAD_INPUT` before any
network call.

---

## 7. Remaining limitations and risks

1. **No live keyed FX execution was performed in this audit.** We verified
   official documentation, endpoint reachability (401 without a key), dynamic
   eligibility and deterministic symbol mapping. Actual keyed OHLCV fetch
   remains **NOT VERIFIED** until an operator supplies a key.
2. **Timeframe coverage is conservative.** The registry advertises `1D` only
   for FX, although both providers support intraday intervals. This avoids
   advertising unverified session/timezone behavior.
3. **Polygon endpoint host.** The adapter still targets legacy
   `https://api.polygon.io`; current Massive docs use `api.massive.com`. Both
   hosts returned 401 on the same path on 2026-11-08, so the legacy host is
   still reachable, but keyed equivalence was not verified.
4. **Free-tier limits can change.** The figures above are vendor-published as
   of 2026-11-08. Operators must re-check before production reliance.
5. **FX pairs are a small curated set.** Only EUR/USD, GBP/USD and USD/JPY are
   registered; other pairs are not silently synthesized.
6. **FX fallback is disabled by design** (section 5).

---

## 8. Release impact

FX support is **not a GO condition**. The release is acceptable with FX
disabled because:

- no FX instrument is advertised unless a real provider is configured;
- unsupported/misconfigured FX requests fail closed with a typed error;
- the limitation and enabling procedure are documented here;
- crypto and equity paths are unaffected.
