# Security Notes — BacktestLab

## Threat Model (15 lines)

1. **Auth**: Local JWT (HS256) with refresh-token rotation + reuse detection.
   Passwords hashed with argon2id (transparent SHA-256 migration for legacy hashes).
   Login rate-limited per IP and per email (20/min). Constant-time comparison on
   password verify. No user enumeration: register/login/forgot all return generic
   messages. `validate_prod_boot()` refuses to start in production unless
   `LOCAL_JWT_SECRET` is ≥32 chars, `CORS_ORIGINS` is not `*`, `DATABASE_URL` is
   not SQLite, and `DEBUG` is off.

2. **Uploads**: CSV upload limited to 5 MB and 5000 rows. Symbol regex
   `^[A-Za-z0-9._-]{1,32}$`. Required OHLC columns + UTC dates + ascending order +
   no duplicates. Formula-injection prefixes (`=`, `+`, `-`, `@`) rejected in any
   cell. No path traversal: the symbol is validated and the file path is built
   server-side (`UPLOAD_DIR/<SYMBOL>.csv`), never from client input.

3. **Provider SSRF**: Data providers only call fixed, allow-listed hostnames
   (stooq.com, query1.finance.yahoo.com, api.binance.com, etc.). No user-
   controlled URLs are ever fetched. `httpx.Client` is configured with a
   connection cap and timeout. Socket-level guard in tests blocks all real
   network connections.

4. **Error leakage**: Stack traces, file paths, SQL, and upstream URLs are never
   returned to the client. The `err()` helper and HTTP exception handler both
   pass messages through `redact_url_keys()`, which strips `?apikey=…`, `&token=…`,
   and `Bearer …` tokens. A log filter redacts the same patterns from server logs.

5. **Headers**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
   `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on auth/result/
   usage/jobs/compare/data-store/billing endpoints.

## Observability (Phase 9)

- `LOG_FORMAT=json|text` and `LOG_LEVEL` control structured logging (stdlib only).
- Every request accepts or generates `X-Request-ID`, stores it in a
  `contextvars` context, echoes it in the response header, and includes it in
  every log line (including worker `job_id`, `backtest_id`, `provider`, `symbol`).
- A logging filter redacts API keys, JWTs, passwords, `Authorization` headers
  and URL query credentials (`apikey`, `token`, `key`, `secret`).
- `/health` is dependency-free liveness; `/ready` checks DB connectivity,
  Alembic head (dev databases created with `create_all` report `unmanaged-dev`)
  and market-store readability; `/metrics` exposes in-process Prometheus text.

## Audit Status

- `pip-audit -r backend/requirements.txt`: clean (no known vulnerabilities)
- AGPL/Affero grep on requirements: clean
- `npm audit --omit=dev --audit-level=high`: clean
- All provider error codes mapped to HTTP status; no silent fallback.

## Owner-only Actions

1. Commercial data provider + redistribution terms: legal review required
   before setting `license_class=commercial_ok`. Not a runtime gate.
2. Supabase URL/keys/JWKS unconfigured: social login unavailable; local JWT
   used instead.
3. Production secrets/CORS/DATABASE_URL: `validate_prod_boot()` enforces at boot.
4. Legal review (privacy, disclaimers, Shariah, Vibe MIT confirm) pending.
5. Hosting + on-device UI review pending.