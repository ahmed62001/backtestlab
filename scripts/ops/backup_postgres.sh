#!/usr/bin/env bash
set -euo pipefail

# Compressed, checksummed PostgreSQL backup with retention pruning.
BACKUP_DIR="${BACKUP_DIR:-${HOME}/.backtestlab-backups/postgres}"
PG_CONTAINER="${PG_CONTAINER:-backtestlab-postgres-1}"
PG_USER="${POSTGRES_USER:-backtestlab}"
PG_DB="${POSTGRES_DB:-backtestlab}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/${PG_DB}_${TS}.sql.gz"

docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" --no-owner --no-acl | gzip -9 > "$OUT_FILE"
chmod 600 "$OUT_FILE"
sha256sum "$OUT_FILE" > "${OUT_FILE}.sha256"
chmod 600 "${OUT_FILE}.sha256"

# Prune backups older than RETENTION_DAYS
find "$BACKUP_DIR" -type f -name "${PG_DB}_*.sql.gz*" -mtime +"$RETENTION_DAYS" -delete

echo "Backup created and checksummed: $OUT_FILE"
