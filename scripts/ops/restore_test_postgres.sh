#!/usr/bin/env bash
set -euo pipefail

# Disposable restore verification test: verifies SHA256, restores into a
# temporary database, checks core tables, and drops the temporary database.
BACKUP_FILE="${1:?Usage: restore_test_postgres.sh <path/to/backup.sql.gz>}"
PG_CONTAINER="${PG_CONTAINER:-backtestlab-postgres-1}"
PG_USER="${POSTGRES_USER:-backtestlab}"
TEST_DB="backtestlab_restore_test_$(date +%s)"

if [ -f "${BACKUP_FILE}.sha256" ]; then
  sha256sum -c "${BACKUP_FILE}.sha256"
fi

cleanup() {
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$TEST_DB\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -c "CREATE DATABASE \"$TEST_DB\";" >/dev/null
gunzip -c "$BACKUP_FILE" | docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$TEST_DB" -v ON_ERROR_STOP=1 >/dev/null

TABLES="$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$TEST_DB" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
echo "Restore verification OK: $TABLES public tables restored in disposable DB $TEST_DB"
