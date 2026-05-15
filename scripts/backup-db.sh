#!/usr/bin/env bash
# backup-db.sh — create a timestamped PostgreSQL dump
# Expected use: ./scripts/backup-db.sh
# Writes to: backups/vortex_<timestamp>.dump
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$ROOT/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/vortex_$TIMESTAMP.dump"

mkdir -p "$BACKUP_DIR"

echo "=== Vortex DB Backup ==="
echo "Timestamp: $TIMESTAMP"
echo "Output: $BACKUP_FILE"

# If running inside Docker, use pg_dump from the postgres container
if [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    # Inside bot container — connect to postgres service
    : "${POSTGRES_DB:?POSTGRES_DB not set}"
    : "${POSTGRES_USER:?POSTGRES_USER not set}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"

    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
        -h postgres \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -Fc \
        --no-owner \
        --no-acl \
        -f "$BACKUP_FILE"
else
    # Running on host — use VORTEX_DATABASE_URL or fallback
    if [ -n "${VORTEX_DATABASE_URL:-}" ]; then
        PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
            -d "$VORTEX_DATABASE_URL" \
            -Fc \
            --no-owner \
            --no-acl \
            -f "$BACKUP_FILE"
    else
        echo "ERROR: VORTEX_DATABASE_URL not set and not in Docker container."
        echo "Run inside Docker: docker compose run --rm bot ./scripts/backup-db.sh"
        exit 1
    fi
fi

echo "Backup created: $BACKUP_FILE"
echo "Size: $(du -h "$BACKUP_FILE" | cut -f1)"
