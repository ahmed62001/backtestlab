# Market Data API Requirements

**Last updated:** 2026-11-13 (real-provider verification pass)
**Scope:** the new market-data read layer (`backend/app/market.py`) and the Overview / Markets / Asset pages.

> **Status update (2026-11-13):** Eighty-eight instruments are registered.
> Twelve Data credentials are now configured and **streaming is verified
> live** (genuine ticks incl. a visible browser update: BTC-USD
> 68,829.02 → 68,837.57). Massive real-time remains entitlement-blocked
> (Basic plan 403s). FRED is a verified macro daily reference. Full
> evidence: `docs/MARKET_STREAMING_IMPLEMENTATION_REPORT.md` and
> `docs/MARKET_ASSET_COVERAGE.md`.

> **Honesty rule used everywhere in this document and in the product:**
> BacktestLab shows *delayed / end-of-day* prices only. No provider below is
> presented as real-time, and no code path fabricates prices. When a provider
> cannot serve a symbol the UI shows an explicit **Unavailable** state.

## How the market layer works today

- `GET /api/v1/market/universe` — no network; the instrument catalog read from the backend registry (`backend/app/instruments.py`).
- `GET /api/v1/market/quotes?symbols=…` (max 40) — one 14-day daily fetch per symbol through the existing provider pipeline (`fetch_bars`) with the default provider (`DATA_PROVIDER_DEFAULT`, `yfinance` in dev). Price = last close, change/pct vs previous close, plus day high/low, volume, `asOf` (last bar timestamp), `source` (actual provider), `quality`. FX pairs (EURUSD/GBPUSD/USDJPY) are served by Frankfurter ECB reference rates with `quality="reference"`; they are **not** backtest-eligible.
- `GET /api/v1/market/series?symbol=&interval=&days=` — normalized OHLCV bars (`{t,o,h,l,c,v}`) with full provenance passthrough (`provider`, `fetched_at`, `cache`, `license_class`, …). Intervals are validated against the serving provider; unsupported intervals return `422 BAD_INPUT` and the UI only offers timeframes the provider declares.
- All three endpoints require authentication (`Depends(current_user)`), consistent with the rest of the API.
- Provider disk cache (24 h default) applies — quote freshness is bounded by it; provenance exposes `cache` hit/miss.
- **WebSocket streaming is now implemented** (`backend/app/streaming.py`, `WS /api/v1/market/stream`, Twelve Data price stream) — see `docs/MARKET_STREAMING_IMPLEMENTATION_REPORT.md`. It needs `TWELVEDATA_API_KEY`; without it the stream reports `not_configured` and the dashboard stays on delayed/EOD REST. Only delayed/EOD data is shown until real provider ticks are verified.

## Provider evaluation

### Wired and verified working without keys (used by the market layer now)

| Provider | Purpose | Docs | Plan | Key | WebSocket | Real-time? | Limitations | Cost | Setup env vars | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **yfinance** (Yahoo Finance) | Default quote/series source: US equities (AAPL/MSFT/NVDA/TSLA/GOOGL/AMZN/META/AMD/SPY/2222.SR/1120.SR), indices (^GSPC/^IXIC/^DJI), commodities (GC=F gold, SI=F silver, CL=F crude), crypto (BTC-USD, ETH-USD). Daily bars = delayed/EOD. | https://pypi.org/project/yfinance/ | Free | Not required | No | **No — delayed / EOD** (Yahoo intraday is unreliable and never labelled live) | ~60 req/min advisory; intraday history limited (~730 days for 1H) | — | `DATA_PROVIDER_DEFAULT=yfinance` (already default) | **Complete** — verified: quotes + series return real bars; any transport failure renders the UI's Unavailable state |
| **Frankfurter** (ECB reference rates) | FX quote display for EURUSD/GBPUSD/USDJPY (`quality="reference"`) | https://frankfurter.dev | Free | Not required | No | No — daily ECB reference rate | Business days only; open=high=low=close; volume 0; **never** used for OHLCV backtesting | — | none | **Complete** — reference quotes only |
| **Binance public / ccxt** | Sub-daily crypto timeframes (1m–1M) for BTC/ETH series when required | https://developers.binance.com/ · https://docs.ccxt.com | Free | Not required | Not wired (REST polling) | No — public REST is delayed as presented | Exchange-specific; needs `ccxt` package | — | Already registered provider #4 | **Complete** for series timeframes; not used for quotes |
| **local_store / local / synthetic / csv_upload** | Dev/demo, offline datasets, user uploads | `docs/DATA_PROVIDERS.md` | — | — | No | No | Dev-only semantics preserved; never presented as market data | — | — | Preserved unchanged |

### Keyed providers already implemented (backtest-eligible where credentialed)

| Provider | Purpose | Docs | Plan | Key | WebSocket | Real-time? | Limitations | Cost | Setup env vars | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **Twelve Data** | Multi-asset EOD/intraday (equities, crypto, FX incl. genuine FX OHLCV for EURUSD/GBPUSD/USDJPY) | https://twelvedata.com/docs | Free tier exists; paid for production volume | Required | Shown as supported by the vendor docs but **not wired** | Free tier is delayed/EOD; real-time is a paid add-on | Free: 8 req/min + daily quota (provider spaces calls 8 s); 15 providers in `docs/DATA_PROVIDERS.md §2` | Free tier free; paid plans per vendor page | `TWELVEDATA_API_KEY` | **Pending credentials** — integration complete, no key configured in CI/dev |
| **Polygon / Massive** | US equities, crypto, FX aggregate bars, adjusted | https://polygon.io/docs | Free Basic tier exists (heavily rate-limited) | Required | Shown as supported by the vendor docs but **not wired** | Free tier delayed 15 min; real-time is paid | Free: 5 req/min (provider spaces calls 12 s); per-asset-class limits (see `docs/FX_PROVIDERS.md`) | Free Basic; paid tiers per vendor page | `POLYGON_API_KEY` | **Pending credentials** — integration complete |
| **Alpha Vantage** | Daily equity/FX/crypto fallback | https://www.alphavantage.co/documentation/ | Free tier (rate-limited) | Required | No | EOD/delayed only | 5 req/min free; daily search quota | Free tier free | `ALPHAVANTAGE_API_KEY` currently empty/missing |
| **FRED** | Macro reference series (display-only context) | https://fred.stlouisfed.org/docs/api/ | Free | Required | No | No — daily macro | 120 req/min | Free | `FRED_API_KEY` | **Pending credentials** (macro not in the market UI yet) |
| **Tiingo** | Adjusted US EOD equities | https://www.tiingo.com/docs | Freemium | Required | Not wired | EOD | Free-tier limits upstream | Freemium per vendor page | `TIINGO_API_KEY` | **Pending credentials** |

### Evaluated, not wired (would need a new provider module + credentials)

| Provider | Purpose | Docs | Plan | Key | WebSocket | Real-time? | Limitations / cost | Setup | Status |
|---|---|---|---|---|---|---|---|---|---|
| **Finnhub** | True real-time US equities + FX + crypto + websocket candles | https://finnhub.io/docs/api | Free tier is delayed/limited; real-time + websocket are paid | Required | Yes (paid) | Only on paid tiers | Free tier rate limits; redistribution restricted to display (not raw data resale) | New `FINNHUB_API_KEY` env var + new provider module | **Blocked on credentials** — evaluate after Phase 0 credentials drop |
| **Financial Modeling Prep (FMP)** | Multi-asset EOD + intraday, index/ETF breadth for movers | https://site.financialmodelingprep.com/developer/docs | Freemium | Required | Yes (paid tiers) | Paid only | Free tier is 250 req/day class limits; licensing display-only | New `FMP_API_KEY` + new provider module | **Blocked on credentials** |
| **Stooq** | Free US EOD CSV fallback (already provider #15) | https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv | Free | Not required | No | No — EOD only | Anti-bot challenges on shared IPs; DB-backed cooldown | Already registered | Complete (backtests); not in the market quote path |

> Pricing amounts are not quoted from memory — confirm current prices on each
> vendor's pricing page before subscribing. Market-data licenses generally
> forbid raw redistribution; BacktestLab only displays quotes and never
> republishes bulk data.

## What I need from you

### Mandatory (to get more than delayed/EOD data)

| # | Item | Why | Where to put it |
|---|---|---|---|
| 1 | **Twelve Data** API key (free tier is enough for evaluation) | Unlocks genuine intraday timeframes (1m–1M) for equities/crypto/FX and FX OHLCV backtesting | `TWELVEDATA_API_KEY` in `backend/.env` / deployment secrets |
| 2 | **Polygon / Massive** API key (free Basic, or a paid market-data plan) | Second multi-asset source; required if any real-time (15-min-delayed) display is wanted | `POLYGON_API_KEY` |

### Optional enhancements

| # | Item | Unlocks |
|---|---|---|
| 3 | **Finnhub** key (paid, for websocket real-time) | True real-time quotes + websocket candles; requires a new provider module + a market-data REST polling → WS transport change |
| 4 | **Financial Modeling Prep** key | Index/ETF breadth feeds for richer movers (Top gainers/losers across the full market, not just the registered universe) |
| 5 | **FRED** key | Macro series (GDP/CPI/rates) as context cards on the Overview page |
| 6 | **Alpha Vantage / Tiingo** keys | Additional EOD fallbacks; redundant while yfinance is healthy |

### Explicitly not required for the current build

- **No API key is required** for the market dashboard as shipped (yfinance + Frankfurter are keyless). The UI honestly labels prices *delayed / end-of-day* and shows **Unavailable** when Yahoo/Frankfurter cannot serve a symbol.
- If no credentials are ever provided, the product stays in the current honest state — delayed/EOD only, no fabricated live prices, no dead controls.

## Next implementation actions (once keys land)

1. Set the env vars above, restart the backend, and verify `GET /api/v1/data-providers` reports `available: true` for Twelve Data / Polygon.
2. Confirm `GET /api/v1/market/quotes?symbols=EURUSD` returns a genuine FX quote (was previously Unavailable with keyed-only providers).
3. Decide on a real-time tier (Finnhub paid) before building any WebSocket transport — do not present REST polling as live.
