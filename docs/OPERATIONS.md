# Operations guide — BacktestLab

This guide covers deployment, configuration, logging/observability, worker
recovery, backups, upgrades/rollbacks and incident procedures. For the data
layer itself see [`DATA_STORE.md`](DATA_STORE.md); for providers see
[`DATA_PROVIDERS.md`](DATA_PROVIDERS.md).

---

## 1. Topology

`docker-compose.yml` defines:

| Service | Image / command | Responsibility |
|---|---|---|
| `postgres` | `postgres:16` | Durable database; volume `pgdata` |
| `migrate` | backend image, `python -m alembic upgrade head` | One-shot schema migration; must complete before API/worker start |
| `backend` | backend image, `uvicorn` (`UVICORN_WORKERS`, default 1) | HTTP API, auth, backtests, in-process async execution |
| `worker` | backend image, `python -m app.worker` | Durable job poller, lease/heartbeat, retries, crash recovery |
| `frontend` | multi-stage nginx image | SPA + `/api/` reverse proxy + security headers |

Ports: frontend `5173`; API `8000` and PostgreSQL `5432` are bound to
`127.0.0.1` only (nginx fronts the API). The `backend` and `worker` share named
volumes for uploads and provider cache so async CSV jobs can read files written
by the API and survive restarts.
`docker compose -f docker-compose.yml -f docker-compose.dev.yml up` enables
hot reload and SQLite by default; `--profile pg` enables PostgreSQL in dev.

SQLite is for development and small single-process deployments only.
Production requires PostgreSQL (`ENV=production` refuses a SQLite URL).

---

## 2. Production configuration and fail-fast

`create_app()` calls `validate_prod_boot()`. With **`ENV=production`** the
process refuses to start (`REFUSE_BOOT: ...`) when any of these is true:

- `LOCAL_JWT_SECRET` is shorter than 32 chars, still `dev-secret-change-me`, or a shipped placeholder such as `change-me-32-chars-minimum-please`;
- `CORS_ORIGINS` contains `*`;
- `DATABASE_URL` starts with `sqlite`;
- `DEBUG=true`;
- `ENGINE_MODE` is not `vendor`;
- `AUTH_RESET_TOKEN_LOG=1`;
- `AUTH_PROVIDER` is anything other than `local` (the JWKS verifier is not wired into the request path, so boot fails closed rather than misleading the operator).

The compose file also refuses to interpolate without `LOCAL_JWT_SECRET` and
`POSTGRES_PASSWORD`; there are no default secrets.

`ENGINE_MODE=vendor` also makes the API and worker verify that the vendored
`GlobalEquityEngine` imports; the worker exits non-zero at startup if it cannot.
A vendor run failure returns `503 ENGINE_UNAVAILABLE` — never a synthetic
fallback.

Minimum production env:

```bash
ENV=production
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/backtestlab
LOCAL_JWT_SECRET=<32+ random chars>
CORS_ORIGINS=https://app.example.com
ENGINE_MODE=vendor
UVICORN_WORKERS=1
TRUST_PROXY_HEADERS=1   # only when the API is reachable solely via nginx
LOG_FORMAT=json
LOG_LEVEL=INFO
```

The full variable table is in the [README](../README.md#environment-variables).
Provider keys are optional; without them those providers report
`available=false` instead of failing the app.

---

## 3. Logging

- `LOG_FORMAT=json|text`. If unset, `json` is used when `ENV=production`,
  otherwise `text`.
- `LOG_LEVEL` defaults to `INFO`.
- JSON records contain `ts`, `level`, `logger`, `message`, optional
  `request_id`, `job_id`, `backtest_id`, `provider`, `symbol`, `duration_ms`,
  `cache`, `status`, `method`, `path`, `rows`, and `exception` for tracebacks.
- The redaction filter strips URL query credentials, `api_key`/`token`/
  `secret`/`password`/`Authorization` values, `Bearer` tokens and standalone
  JWTs from messages and exception text. `redact_url_keys()` applies the same
  rules to API error messages.
- Request logging: method, route template, status and duration, plus the
  `X-Request-ID` response header (valid client value accepted, otherwise a
  128-bit hex id is generated).
- **No duplicate access logs:** the structured request log is the source of
  truth, so uvicorn's plain access line is disabled in the Docker images
  (`--no-access-log`) and suppressed by default when running the app
  (`UVICORN_ACCESS_LOG=0`). Set `UVICORN_ACCESS_LOG=1` only if you want both.
- **Probe noise:** unmatched paths such as `GET /v1/models` are logged at most
  once per client/path per `PROBE_LOG_INTERVAL_S` (default 300 s), with
  client, user-agent, query and request id. They are ignored otherwise so they
  cannot drown real traffic.
- **Backtest timing:** `POST /backtests` logs one structured line with
  `validate_ms`, `data_ms`, `engine_ms`, `persist_ms` and `total_ms`, which
  makes upstream slowness distinguishable from validation/engine time.
- Worker logging adds job context and `cache=hit|miss|partial` derived from
  provenance (`retrieval` is mapped: `store→hit`, `partial→partial`,
  `live→miss`).

Logs go to stdout; ship them with the platform's log collector.

---

## 4. Health, readiness and metrics

| Endpoint | Purpose | Behavior |
|---|---|---|
| `GET /health` | Liveness | `{ok, service, time}`; no DB/store/vendor dependency |
| `GET /api/v1/health` | Back-compat liveness | `{ok:true}` |
| `GET /ready` | Readiness | Checks DB (`SELECT 1`), Alembic head, store readability, vendor availability; HTTP 503 when not ready |
| `GET /metrics` | Prometheus | `text/plain; version=0.0.4`, in-process counters |
| `GET /docs-contract` | Contract version | `{version}` |

`/ready` migration values: `head` (good), `unmanaged-dev` (no
`alembic_version`; tolerated outside production), `behind` (503), `error`
(503 in production, reported otherwise). Vendor is reported as
`{available, detail}` but does not fail readiness by itself.

Metrics:

| Metric | Labels | Meaning |
|---|---|---|
| `backtestlab_http_requests_total` | `method`, `path`, `status` | Request count |
| `backtestlab_http_request_duration_ms_sum` / `_count` | `method`, `path` | Duration sum/count for averages |
| `backtestlab_jobs_total` | `status` (`queued`, `done`, `failed`, `retried`, `timeout`) | Job outcomes |
| `backtestlab_jobs_recovered_total` | — | Stale jobs requeued |
| `backtestlab_jobs_recovery_failed_total` | — | Stale jobs failed after retries |

The registry is per process. With multiple uvicorn workers/worker replicas,
scrape each process (or aggregate in Prometheus), and expect counters to reset
on restart.

Docker healthchecks: backend `/health`; frontend `/nginx-health`; worker writes
`WORKER_ALIVE_FILE` (`/tmp/worker.alive`) and the compose healthcheck fails if
it is older than 30 s.

---

## 5. Worker lifecycle and recovery

Jobs live in the `jobs` table (`queued → running → done|failed|cancelled`).
`POST /api/v1/backtests?async=true` (or a request with `Idempotency-Key`)
creates a row and starts an in-process executor thread in the API; the separate
`worker` service also polls `queued` rows. Both use the same atomic claim, so a
job is executed once.

Reliability contract:

- **Claim:** atomic compare-and-set `queued → running` with `attempts += 1`,
  `worker_id`, `started_at`, `heartbeat_at`, `lease_expires_at`.
- **Heartbeat:** a daemon thread extends the lease every
  `min(JOB_HEARTBEAT_SECONDS, JOB_LEASE_SECONDS/3)`.
- **Crash recovery:** `recover_stale_jobs()` runs at worker startup and every
  `JOB_RECOVERY_INTERVAL_S` (default 30 s). Expired running jobs are requeued
  with backoff while `attempts < max_attempts`; otherwise they fail with
  `LEASE_EXPIRED` and the daily quota is refunded.
- **Retries:** transient provider failures (`UPSTREAM_*`, `RATE_LIMITED`,
  `PROVIDER_DOWN`, `PROVIDER_TIMEOUT`) requeue up to `JOB_MAX_ATTEMPTS` with
  `JOB_RETRY_BACKOFF_S × attempts`. Validation failures are terminal.
- **Timeout:** compute runs in a daemon thread; after `JOB_TIMEOUT_SECONDS`
  the job fails with `TIMEOUT:` and no result is written.
- **Idempotent writes:** results are persisted only while the worker still owns
  the running lease; a replayed job cannot overwrite a `done` backtest or
  double-count usage.
- **Graceful shutdown:** first SIGTERM lets the in-flight job finish and exits 0;
  a second SIGTERM requeues the job and exits immediately.

Inspection SQL:

```sql
-- stuck / queued work
SELECT id, status, attempts, max_attempts, next_attempt_at,
       lease_expires_at, heartbeat_at, worker_id, error
FROM jobs
WHERE status IN ('queued', 'running')
ORDER BY created_at;

-- expired leases
SELECT id, status, worker_id, lease_expires_at
FROM jobs
WHERE status = 'running' AND lease_expires_at <> '' AND lease_expires_at < now();
```

A job recovered by the queue runner does not need manual action. If a job is
`failed` with `LEASE_EXPIRED`, retries were exhausted; check the error, fix the
cause, and allow the user to resubmit.

---

## 6. Backups

Take a database backup before every upgrade and on a schedule (e.g. hourly
WAL/binlog or daily logical dump, retained per policy).

### PostgreSQL

```bash
docker compose exec -T postgres pg_dump -Fc -U backtestlab backtestlab \
  > /backup/bt-$(date +%F-%H%M).dump

# restore into an empty database
docker compose exec -T postgres pg_restore --clean --if-exists \
  -U backtestlab -d backtestlab < /backup/bt-2026-11-04-1200.dump
```

### SQLite

```bash
sqlite3 backend/backtestlab.db ".backup '/backup/bt-$(date +%F-%H%M).db'"
# stop API + worker before restoring (copy .db, .db-wal, .db-shm together)
sqlite3 backend/backtestlab.db "PRAGMA integrity_check;"
```

Provider disk caches (`DATA_CACHE_DIR`) and uploaded CSVs (`DATA_UPLOAD_DIR`)
are disposable; they are not part of the database backup. See
[`DATA_STORE.md`](DATA_STORE.md#backup-and-restore) for store verification after
restore.

---

## 7. Upgrade procedure

1. **Record the current state:** `python -m alembic current`,
   `git log --oneline -1`, image tags.
2. **Back up** the database (section 6) and verify the dump exists.
3. **Build/pull** the new images:
   `docker compose build` or `docker compose pull`.
4. **Migrate** with the one-shot service (compose starts `migrate`
   automatically) or manually:
   `docker compose run --rm migrate` / `python -m alembic upgrade head`.
5. **Start/restart** `backend` and `worker`.
6. **Verify:** `curl -fsS .../health`, `curl -fsS .../ready` (`migrations.head`,
   `db.ok`, `store.ok`), check `/metrics`, run one seeded backtest / E2E smoke.
7. **Monitor** error rate, job failures and `backtestlab_jobs_recovered_total`
   for one interval.

Migrations are additive unless noted; always read the migration before
upgrading a production database.

---

## 8. Rollback procedure

1. **Application-only rollback:** redeploy the previous image tag; the schema
   is usually backward-compatible within a release.
2. **Schema rollback:** only with a backup and a planned target.
   Current head is `c3e9f1a2b4d6`; the previous release head was
   `9c4e7a2b1f30`. The two Phase 15 migrations are additive
   (`b1a7c3d9e2f4` adds `auth_attempts`, `c3e9f1a2b4d6` adds `provider_state`).
   The release-tested destructive baseline is:

   ```bash
   python -m alembic downgrade 5d8a7492f5a8   # drops reliability, store and provenance data
   python -m alembic upgrade head
   ```

   For a production rollback prefer a database restore from the pre-upgrade
   dump over an ad-hoc multi-step downgrade.
3. **Verify** `/ready` and a backtest after rollback.

Never downgrade a production database without a verified backup.

---

## 9. Incident procedures

### `/ready` returns 503

Read the body: `db`, `migrations`, `store`, `vendor`.

| Field | Action |
|---|---|
| `db: error` | Check database availability, credentials, pool exhaustion (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`), network. |
| `migrations: behind/error` | Run `alembic upgrade head` (or inspect `alembic current`); do not serve traffic on a behind schema. |
| `store: error` | Check that `market_instruments` is readable; restore/repair the DB. |
| `vendor.available=false` | Check `backend/vendor/Vibe-Trading`, the pinned engine import and container image contents. |

### Jobs stuck queued

Check `next_attempt_at` (backoff), whether a worker is running, and whether
`ENGINE_MODE`/provider deps are valid in the worker container. The worker logs
`worker loop error` with a traceback on repeated failures.

### Jobs stuck running with an expired lease

This is the crash path; `recover_stale_jobs()` should requeue or fail them
within `JOB_RECOVERY_INTERVAL_S`. If the worker is dead, restart it; if no
worker runs, start one or submit via the API (in-process executor).

### Provider outage / `UPSTREAM_BLOCKED`

A compatible real provider may be tried automatically when
`DATA_PROVIDER_FALLBACK=1` (default); the result provenance shows
`fallback=true`, `fallback_from` and `fallback_reason`. There is never a
synthetic substitution, and FX is not substituted across providers. Inspect the
provider error, the catalog availability and the provider key/package. Options:
retry later, switch the request's `dataProvider`, or use `local_store` if the
range is already stored. Set `DATA_PROVIDER_FALLBACK=0` to require the selected
provider. Verify with `backend/scripts/smoke_providers.py`.

**Anti-bot cooldown:** an `UPSTREAM_BLOCKED` (for example Stooq's challenge
page) parks that provider for `PROVIDER_COOLDOWN_S` (default 300 s) in the shared
database. The catalog then reports `available=false` with an `availableDetail`
and `retryAfter`; requests that explicitly select it fail fast with
`503 PROVIDER_COOLDOWN` instead of re-hitting the challenge. No manual action is
needed — it clears itself. To inspect or clear early:

```sql
SELECT provider_id, reason, cooldown_until, updated_at FROM provider_state;
DELETE FROM provider_state WHERE provider_id = 'stooq';  -- optional early clear
```

**No data vs. outage:** a valid but empty upstream response is
`422 PROVIDER_NO_DATA` (provider, symbol, range, `retryAfter` in the body), not
a `5xx`. It is never retried. Verify the symbol/range actually has data at the
upstream before treating it as an incident.

### Disk full

The provider disk cache (`DATA_CACHE_DIR`), uploaded CSVs (`DATA_UPLOAD_DIR`)
and SQLite WAL can fill a small disk. Remove stale cache files or move the
directories; never delete the live database/WAL while the app is running.

### Auth incidents

- Rotate `LOCAL_JWT_SECRET` → all access/refresh tokens become invalid (users
  must log in again).
- Revoke refresh tokens for a user: `POST /api/v1/auth/revoke` with a valid
  access token, or delete/revoke rows in `refresh_tokens`.
- **Login lockout is shared through the database** (table `auth_attempts`):
  `LOGIN_MAX_ACCOUNT_FAILURES` (default 5) per account within
  `LOGIN_FAILURE_WINDOW_S` (default 900 s), and `LOGIN_MAX_IP_FAILURES`
  (default 20) per client IP in the same window. Locked logins return `429`
  with `Retry-After`; a successful login clears that account's failures.
  Unknown accounts still pay a dummy Argon2 verification, so response time does
  not reveal whether an email exists. To clear a lockout early, delete the
  matching rows from `auth_attempts` (inspect `scope`, `key`, `created_at`).

### Data corruption

`python -m app.cli verify` recomputes coverage hashes and exits non-zero on
mismatch. Identify the affected instrument/provider/range, re-ingest it, or
purge and refill. Do not edit `data_hash` manually. For PostgreSQL, run
`VACUUM (ANALYZE)` after large purges.

---

## 10. Scaling notes and known limitations

- Run PostgreSQL and multiple worker replicas for durable async work; the
  atomic claim makes concurrent workers safe.
- API replicas share the database but each has its own in-process metrics and
  disk cache. Uploaded CSVs are stored in the API container's
  `DATA_UPLOAD_DIR`; the separate worker container does **not** share that
  directory by default. For `csv_upload` jobs across containers, mount a shared
  volume or keep execution in the API process. Provider API keys must be set on
  both API and worker.
- `DATA_CACHE_DIR` is also per container; a cache miss is a performance cost,
  not a correctness issue.
- SQLite is single-writer; do not run multiple containers or high-concurrency
  workloads against one SQLite file.
- **Queue slot / kill-switch state is process-local** (`UVICORN_WORKERS=1` is the
  supported configuration). Multiple API replicas would each have their own
  slot counter, so keep `UVICORN_WORKERS=1` until this moves to the DB/queue.
- The catalog snapshot and provider cooldown are shared through the database,
  but the in-process provider HTTP de-duplication and rate spacing are
  per-process.
- **Billing is disabled by default.** `BILLING_ENABLED=false` (no payment
  provider installed) makes checkout/portal return `501 BILLING_NOT_CONFIGURED`,
  the webhook `503`, and the UI disables the upgrade button.
- **Vendor integrity:** `make verify-vendor` (or
  `python backend/scripts/verify_vendor.py`) checks the vendored engine against
  `backend/vendor/Vibe-Trading/SHA256SUMS`. Run it in CI and after any vendor
  update; CI runs it automatically.
- See [`SECURITY_NOTES.md`](SECURITY_NOTES.md) for the threat model and
  owner-only security items.
