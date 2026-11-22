# BacktestLab — Deployment

All commands below were executed during the `20261117T010400Z` release run on
this machine. Anything not executed is explicitly marked **untested**.

## 1. Prerequisites
- Docker 28.5.2 and Docker Compose 2.40.3 (tested versions).
- A `.env` file in the repository root (never committed) with at least:

```dotenv
POSTGRES_PASSWORD=<strong random value>
LOCAL_JWT_SECRET=<32+ random characters, not a placeholder>
CORS_ORIGINS=https://your-host.example
ENV=production
```

`POSTGRES_PASSWORD` and `LOCAL_JWT_SECRET` are mandatory: compose fails to
interpolate without them, and the API refuses to boot in production with a
placeholder or a short signing secret.

## 2. Build and start

```bash
docker compose build backend frontend
docker compose up -d
docker compose ps
```

Expected: `postgres`, `backend`, `worker`, `frontend` healthy; `migrate` exits
`0`. The API binds `127.0.0.1:8000`, Postgres `127.0.0.1:5432`, the frontend
`0.0.0.0:5173` (put a TLS ingress in front of it).

## 3. Verify health, readiness and migrations

```bash
curl -sS -o /dev/null -w '%{http_code}\n' localhost:8000/health   # 200
curl -sS localhost:8000/ready                                     # {"ok":true,...,"migrations":{"status":"head",...}}
docker compose exec -T backend alembic current                    # c3e9f1a2b4d6 (head)
docker compose exec -T backend alembic heads                      # c3e9f1a2b4d6 (head)
```

`/ready` returns **503** when the database is unreachable (verified by stopping
Postgres) and **200** again after it returns.

## 4. Migrations

The `migrate` service runs `python -m alembic upgrade head` on every `up`.
To run it manually:

```bash
docker compose run --rm migrate
```

Verified in this run: an empty database upgrades to `c3e9f1a2b4d6`, a database
restored from the Phase 0 dump upgrades to head, and `alembic check` reports no
model/migration drift.

## 5. Restart and persistence

```bash
docker compose restart backend worker
```

Verified: run ids, metrics and equity curves are unchanged after the restart.

## 6. Backup and restore

```bash
# Backup (run inside the postgres container so no password is printed)
docker compose exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > backup.dump

# Restore into a scratch database (create it first)
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -c 'CREATE DATABASE restore_check'
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d restore_check --no-owner --no-privileges < backup.dump
```

Verified: row counts matched after restore.

## 7. Clean verification stack (no data loss)

Build and start a separate project with an override file **outside** the repo:

```yaml
# compose.verify.yml
services:
  postgres:
    ports: !override ["127.0.0.1:15432:5432"]
  backend:
    ports: !override ["127.0.0.1:18000:8000"]
  frontend:
    ports: !override ["127.0.0.1:15173:80"]
```

```bash
docker compose -p backtestlab-verify -f docker-compose.yml -f compose.verify.yml build --no-cache backend frontend
docker compose -p backtestlab-verify -f docker-compose.yml -f compose.verify.yml up -d
docker compose -p backtestlab-verify -f docker-compose.yml -f compose.verify.yml ps -a
```

Use `!override` so the port lists are replaced rather than appended (otherwise
the host ports collide with the running stack). Tear down with
`docker compose -p backtestlab-verify ... down` (no `-v`; volumes are kept).

## 8. Operational notes
- Run exactly one `backend` and one `worker` replica (in-process queue and rate
  limiter). `UVICORN_WORKERS` must stay `1`.
- Set `TRUST_PROXY_HEADERS=1` only when a reverse proxy you control sets
  `X-Real-IP`/`X-Forwarded-For`.
- Terminate TLS at the ingress; add HSTS there. The bundled nginx config does
  not terminate TLS.
- Do not expose the backend or Postgres ports publicly; both are loopback-bound.

## 9. Untested
- Real TLS termination, DNS, and external load balancer configuration.
- Multi-replica deployment (explicitly unsupported).
- Payment provider integration (billing is disabled by design).
