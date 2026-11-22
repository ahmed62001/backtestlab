# Runbook

- Boot: `DATABASE_URL=... LOCAL_JWT_SECRET=... uvicorn app.main:app --port 8000` (from backend/).
- Reset user limit: delete usage row for (user_id, today UTC).
- Inspect failed job: GET /api/v1/backtests/{id}; validation never consumes quota; 429 includes DAILY_LIMIT_REACHED.
- Rotate keys: set new LOCAL_JWT_SECRET (sessions invalidate).
- Upgrade vendor: re-clone, update VIBE_TRADING_VERSION + THIRD_PARTY_NOTICES, rerun pytest golden (determinism test).

## Worker reliability (Phase 10)

- Every job is claimed with an atomic `queued -> running` update and carries a
  lease (`lease_expires_at`) refreshed by a heartbeat every
  `JOB_HEARTBEAT_SECONDS` (default 15s, max one third of the lease).
- A worker that dies (kill -9, OOM, container eviction) leaves an expired lease.
  `recover_stale_jobs()` runs on worker startup and every
  `JOB_RECOVERY_INTERVAL_S` (default 30s): it requeues the job with backoff while
  `attempts < max_attempts`, then fails it with a safe `LEASE_EXPIRED` message
  and refunds the daily quota.
- `JOB_MAX_ATTEMPTS` (default 3) bounds retries for *transient* upstream
  failures (`UPSTREAM_*`, `RATE_LIMITED`, `PROVIDER_DOWN/TIMEOUT`). Validation
  failures are terminal and never retried.
- `JOB_TIMEOUT_SECONDS` (default 120) bounds one execution. The compute step is
  abandoned in a daemon thread; the job is failed with `TIMEOUT:` and the
  result is never written.
- Graceful shutdown: the first SIGTERM lets the in-flight job finish and exits 0.
  A second SIGTERM releases the job back to `queued` and exits immediately.
- Inspect stuck work: `SELECT id,status,attempts,lease_expires_at,error FROM jobs
  WHERE status IN ('queued','running') ORDER BY created_at;`

## Database tuning (Phase 10)

- SQLite (dev): `PRAGMA journal_mode=WAL`, `busy_timeout` (`SQLITE_BUSY_TIMEOUT_MS`,
  default 5000), `synchronous=NORMAL`, foreign keys on.
- PostgreSQL: `pool_pre_ping`, `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10),
  `DB_POOL_RECYCLE_S` (1800), `DB_POOL_TIMEOUT_S` (30), and a server-side
  `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`, default 30000).
- Hot queries use `ix_backtests_user_created`, `ix_jobs_status_lease`,
  `ix_jobs_status_next_attempt` and `ix_usage_user_day`. Re-check with
  `EXPLAIN (ANALYZE, COSTS OFF)` after schema changes.
- API responses are bounded: `/api/v1/backtests` defaults to 50 rows (max 200,
  `limit`/`offset`), equity is downsampled to `API_MAX_EQUITY_POINTS` (1000) and
  trades to `API_MAX_TRADE_ROWS` (500) with `resultMeta` describing what was
  trimmed. `/api/v1/compare` accepts at most 10 ids.

## Browser E2E (Phase 11)

- Run `npm run e2e` (or `make e2e`) from the repo root. Playwright starts both
  servers: `e2e/start-backend.sh` (throwaway SQLite DB at
  `/tmp/backtestlab_e2e.db`, `python -m app.cli seed`, `ENGINE_MODE=vendor`,
  `DATA_PROVIDER_DEFAULT=local_store`) and Vite with `VITE_USE_MOCK=false`.
- No network or provider keys are needed; tests use the seeded synthetic bars
  through `local_store`. The error-path spec requests a range that was not
  seeded and expects the translated `DATA_NOT_IN_STORE` message.
- Ports: `E2E_API_PORT` (default 8000) and `E2E_WEB_PORT` (default 5173). Set
  `E2E_DB` to use a different SQLite file.
- On failure, inspect `test-results/` (screenshot, video, trace) and
  `playwright-report/`. CI uploads both as artifacts. Local trace viewer:
  `npx playwright show-trace test-results/<test>/trace.zip`.
