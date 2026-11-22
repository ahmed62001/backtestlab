#!/usr/bin/env bash
# Start an isolated, seeded backend for the Playwright E2E suite (Phase 11).
#
# Uses a throwaway SQLite database + the in-process vendor engine, seeds the
# market-data store with deterministic synthetic bars (no network/keys), and
# exposes local_store as the default provider so the wizard can complete
# offline.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

DB="${E2E_DB:-/tmp/backtestlab_e2e.db}"
PORT="${E2E_API_PORT:-8000}"
CACHE_DIR="${E2E_CACHE_DIR:-/tmp/backtestlab_e2e_cache}"

rm -f "$DB" "$DB-wal" "$DB-shm"
rm -rf "$CACHE_DIR"

export DATABASE_URL="sqlite:///$DB"
export ENV="${ENV:-dev}"
export ENGINE_MODE="${ENGINE_MODE:-vendor}"
export DATA_PROVIDER_DEFAULT="${DATA_PROVIDER_DEFAULT:-local_store}"
export DATA_PROVIDERS_ENABLED="${DATA_PROVIDERS_ENABLED:-local_store,synthetic,local,alphavantage,csv_upload}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://127.0.0.1:5173,http://localhost:5173}"
export DATA_CACHE_DIR="$CACHE_DIR"
export LOG_FORMAT="${LOG_FORMAT:-text}"

python -m app.cli seed --start 2022-01-01 --end 2023-12-31
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
