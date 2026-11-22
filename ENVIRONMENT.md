# BacktestLab — Environment Variables

Every variable read by the backend, the frontend build, or the compose files is
listed here. The “In example” column records whether a placeholder exists in
`.env.example` or `backend/.env.example` (verified in this run; inventory:
`final-release-evidence/security/env-inventory.json`).

Production-critical values: `POSTGRES_PASSWORD`, `LOCAL_JWT_SECRET`,
`CORS_ORIGINS`, `ENV=production`, `DATABASE_URL`. The API refuses to boot in
production with a weak/placeholder signing secret, `CORS *`, SQLite, `DEBUG`,
a non-`vendor` engine, reset-token logging, or a non-local auth provider.

| Variable | Purpose | In example |
|---|---|---|
| `ALPHAVANTAGE_API_KEY` | Optional Alpha Vantage API key (keyed provider). | yes |
| `API_DEFAULT_PAGE_SIZE` | Default page size for list endpoints. | yes |
| `API_MAX_COMPARE_IDS` | Maximum run ids accepted by /compare. | yes |
| `API_MAX_EQUITY_POINTS` | Maximum equity points returned by the API (downsampled beyond this). | yes |
| `API_MAX_PAGE_SIZE` | Maximum page size for list endpoints. | yes |
| `API_MAX_TRADE_ROWS` | Maximum trade rows returned by the API. | yes |
| `AUTH_PROVIDER` | Identity provider. Must be `local` for production boot. | yes |
| `AUTH_RESET_TOKEN_LOG` | If 1, logs password-reset tokens (development only; production refuses). | yes |
| `BILLING_ENABLED` | Enables billing endpoints. Default false; endpoints return 501 when disabled. | yes |
| `CCXT_EXCHANGE` | CCXT exchange id for the ccxt provider (default binance). | yes |
| `COINGECKO_COIN_LIST_TTL_S` | CoinGecko coin-id cache TTL (seconds). | yes |
| `CORS_ORIGINS` | Comma-separated allowed browser origins. `*` is refused in production. | yes |
| `DAILY_RUN_LIMIT_FREE` | Backtests per day on the free plan. | yes |
| `DAILY_RUN_LIMIT_PRO` | Backtests per day on the pro plan. | yes |
| `DATABASE_URL` | SQLAlchemy database URL (compose builds a PostgreSQL URL). | yes |
| `DATA_CACHE_DIR` | On-disk provider cache directory. | yes |
| `DATA_CACHE_TTL_S` | Provider cache TTL (seconds). | yes |
| `DATA_FETCH_BACKOFF_S` | Base retry backoff for provider fetches (seconds). | yes |
| `DATA_FETCH_RETRIES` | Provider fetch retry attempts. | yes |
| `DATA_PROVIDERS_ENABLED` | Comma-separated provider ids enabled at runtime. | yes |
| `DATA_PROVIDER_DEFAULT` | Default market-data provider id. | yes |
| `DATA_PROVIDER_FALLBACK` | Optional ordered fallback provider ids. | yes |
| `DATA_RETRY_MAX_WAIT_S` | Cap for a single Retry-After/backoff sleep (seconds). | yes |
| `DATA_STORE_TTL_DAILY_DAYS` | TTL for cached daily bars in the data store (days). | yes |
| `DATA_STORE_TTL_INTRADAY_MINUTES` | TTL for cached intraday bars (minutes). | yes |
| `DATA_STORE_TTL_RECENT_HOURS` | TTL for recently fetched data (hours). | yes |
| `DATA_UPLOAD_DIR` | CSV upload storage directory (per-user quarantine subdirectories). | yes |
| `DB_MAX_OVERFLOW` | SQLAlchemy pool max overflow. | yes |
| `DB_POOL_RECYCLE_S` | SQLAlchemy pool recycle (seconds). | yes |
| `DB_POOL_SIZE` | SQLAlchemy pool size. | yes |
| `DB_POOL_TIMEOUT_S` | SQLAlchemy pool checkout timeout (seconds). | yes |
| `DB_STATEMENT_TIMEOUT_MS` | PostgreSQL statement timeout (ms). | yes |
| `DEBUG` | Debug flag. Must be false in production. | yes |
| `ENGINE_MODE` | `vendor` in production; `local`/synthetic is development only. | yes |
| `ENV` | `dev` or `production`; production enables fail-fast configuration checks. | yes |
| `FRED_API_KEY` | Optional FRED API key (macro reference series). | yes |
| `JOB_HEARTBEAT_SECONDS` | Worker heartbeat interval for job leases (seconds). | yes |
| `JOB_LEASE_SECONDS` | Job lease duration before another worker may recover it (seconds). | yes |
| `JOB_MAX_ATTEMPTS` | Maximum attempts before a job is marked failed. | yes |
| `JOB_RECOVERY_INTERVAL_S` | Interval for recovering stale jobs (seconds). | yes |
| `JOB_RETRY_BACKOFF_S` | Backoff before retrying a transient job failure (seconds). | yes |
| `JOB_TIMEOUT_S` | Job execution timeout used by the worker (seconds). | yes |
| `JOB_TIMEOUT_SECONDS` | Job timeout used by the API/worker configuration (seconds). | yes |
| `JWT_ACCESS_MIN` | Access-token lifetime (minutes). | yes |
| `JWT_REFRESH_DAYS` | Refresh-token lifetime (days). | yes |
| `LOCAL_JWT_SECRET` | JWT signing secret. 32+ random characters; placeholders are refused in production. | yes |
| `LOGIN_FAILURE_WINDOW_S` | Login lockout window (seconds). | yes |
| `LOGIN_MAX_ACCOUNT_FAILURES` | Failed logins per account before lockout. | yes |
| `LOGIN_MAX_IP_FAILURES` | Failed logins per IP before lockout. | yes |
| `LOGIN_MAX_PER_MIN` | Login attempts per minute per IP. | yes |
| `LOG_FORMAT` | `json` in containers, `text` for local development. | yes |
| `LOG_LEVEL` | Application log level. | yes |
| `MARKET_QUOTE_WORKERS` | Bounded concurrency for the multi-symbol quote sweep. | yes |
| `MARKET_STREAMING_ENABLED` | Enables Twelve Data WebSocket streaming (needs a key). | yes |
| `MARKET_STREAM_MAX_SUBSCRIPTIONS` | Maximum simultaneous stream subscriptions. | yes |
| `MASSIVE_API_KEY` | Preferred Massive API key (Massive / Polygon.io keyed provider). | yes |
| `MAX_BARS` | Maximum bars retained per provider frame. | yes |
| `MAX_UPLOAD_ROWS` | Maximum rows accepted in a CSV upload. | yes |
| `P15_TEST_PG_HOST` | Test-only: PostgreSQL host allowed through the socket guard. | yes |
| `P15_TEST_PG_PORT` | Test-only: PostgreSQL port allowed through the socket guard. | yes |
| `P15_TEST_PG_SOCKET_DIR` | Test-only: PostgreSQL Unix-socket directory allowed through the guard. | yes |
| `PASSWORD_RESET_TTL_MIN` | Password-reset token lifetime (minutes). | yes |
| `POLYGON_API_KEY` | Optional Polygon API key (keyed provider). | yes |
| `POSTGRES_DB` | Compose: PostgreSQL database name. | yes |
| `POSTGRES_PASSWORD` | Compose: PostgreSQL password (required, never commit a real value). | yes |
| `POSTGRES_USER` | Compose: PostgreSQL user. | yes |
| `PROBE_LOG_INTERVAL_S` | Minimum interval between unmatched-probe log lines (seconds). | yes |
| `PROVIDER_CATALOG_CACHE` | Cache the provider health catalog (1/0). | yes |
| `PROVIDER_CATALOG_TTL_S` | Provider catalog snapshot TTL (seconds). | yes |
| `PROVIDER_COOLDOWN_S` | Shared anti-bot/rate-limit cooldown per provider (seconds). | yes |
| `PROVIDER_HEALTH_TIMEOUT_S` | Provider health probe timeout (seconds). | yes |
| `PUBLIC_MARKET_DEFAULT_LIMIT` | Default candle count for the public chart. | yes |
| `PUBLIC_MARKET_DEFAULT_SYMBOL` | Default symbol for the public chart. | yes |
| `PUBLIC_MARKET_MAX_BARS` | Hard maximum candles returned publicly. | yes |
| `PUBLIC_MARKET_PROVIDER` | Provider used by the public (pre-login) endpoint. | yes |
| `PUBLIC_MARKET_RATE_LIMIT` | Public requests per IP per 60 s window. | yes |
| `QUEUE_MAX_WORKERS` | In-process worker concurrency cap. | yes |
| `QUEUE_RECOVER_ON_SUBMIT` | Recover stale jobs when a job is submitted (1/0). | yes |
| `RATE_LIMIT_MAX_KEYS` | Cap on in-process rate-limiter keys. | yes |
| `SQLITE_BUSY_TIMEOUT_MS` | SQLite busy timeout for development databases (ms). | yes |
| `SUPABASE_AUDIENCE` | Optional Supabase JWT audience (verifier not wired into requests). | yes |
| `SUPABASE_ISSUER` | Optional Supabase JWT issuer. | yes |
| `SUPABASE_JWKS_URL` | Optional Supabase JWKS URL (http/https only). | yes |
| `TIINGO_API_KEY` | Optional Tiingo API key (keyed provider). | yes |
| `TRUST_PROXY_HEADERS` | Trust X-Real-IP/X-Forwarded-For only behind a proxy you control (1/0). | yes |
| `TWELVEDATA_API_KEY` | Optional Twelve Data API key (keyed provider / streaming). | yes |
| `TWELVEDATA_WS_URL` | Twelve Data WebSocket URL (server-side only). | yes |
| `UVICORN_ACCESS_LOG` | Emit uvicorn access lines in addition to structured logs (1/0). | yes |
| `UVICORN_WORKERS` | Uvicorn workers. Must stay 1 (in-process queue and rate limiter). | yes |
| `VITE_API_BASE` | Frontend API base URL; empty means same-origin. | yes |
| `VITE_APP_NAME` | Frontend product name. | yes |
| `VITE_USE_MOCK` | Frontend mock mode. Must be false for real data. | yes |
| `WORKER_ALIVE_FILE` | Heartbeat file written by the worker. | yes |
| `WORKER_ID` | Optional stable worker id (defaults to a generated id). | yes |
| `WORKER_POLL_SECONDS` | Worker queue poll interval (seconds). | yes |

## Notes
- Values shown in `.env.example` are placeholders, not credentials.
- `P15_TEST_PG_*` are test-harness only and are ignored by the application.
- `VITE_*` values are compiled into the frontend bundle; never put secrets there.
- `SUPABASE_*` variables are optional and the Supabase verifier is not wired into
  the request path; production requires `AUTH_PROVIDER=local`.
