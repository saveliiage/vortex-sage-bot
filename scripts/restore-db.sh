#!/usr/bin/env bash
# restore-db.sh — restore a PostgreSQL dump
# Expected use: ./scripts/restore-db.sh backups/<file>.dump
# WARNING: DESTRUCTIVE — overwrites current database!
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ $# -lt 1 ]; then
    echo "Usage: ./scripts/restore-db.sh <backup-file.dump>"
    echo ""
    echo "Available backups:"
    if [ -d "$ROOT/backups" ]; then
        ls -1 "$ROOT/backups/"*.dump 2>/dev/null || echo "  (none)"
    else
        echo "  (none)"
    fi
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "============================================"
echo "  ⚠️  DESTRUCTIVE OPERATION  ⚠️"
echo "============================================"
echo ""
echo "This will OVERWRITE the current Vortex database"
echo "with the contents of: $BACKUP_FILE"
echo ""
echo "Size: $(du -h "$BACKUP_FILE" | cut -f1)"
echo "Date: $(stat -c '%y' "$BACKUP_FILE" 2>/dev/null || echo 'unknown')"
echo ""
echo "============================================"

if [ -t 0 ]; then
    read -r -p "Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
fi

echo ""
echo "=== Vortex DB Restore ==="

# If running inside Docker
if [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    : "${POSTGRES_DB:?POSTGRES_DB not set}"
    : "${POSTGRES_USER:?POSTGRES_USER not set}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"

    # Drop and recreate so restore is clean
    PGPASSWORD="$POSTGRES_PASSWORD" dropdb \
        -h postgres \
        -U "$POSTGRES_USER" \
        --if-exists \
        "$POSTGRES_DB"

    PGPASSWORD="$POSTGRES_PASSWORD" createdb \
        -h postgres \
        -U "$POSTGRES_USER" \
        "$POSTGRES_DB"

    PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
        -h postgres \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --no-owner \
        --no-acl \
        "$BACKUP_FILE"
else
    if [ -n "${VORTEX_DATABASE_URL:-}" ]; then
        # Parse DATABASE_URL to get components
        echo "Restoring to: ${VORTEX_DATABASE_URL%%@*}@***"

        PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_restore \
            -d "$VORTEX_DATABASE_URL" \
            --no-owner \
            --no-acl \
            --clean \
            --if-exists \
            "$BACKUP_FILE"
    else
        echo "ERROR: VORTEX_DATABASE_URL not set and not in Docker container."
        echo "Run inside Docker: docker compose run --rm bot ./scripts/restore-db.sh <file>"
        exit 1
    fi
fi

echo ""
echo "Restore complete."
echo "Run migrations after restore: ./scripts/migrate.sh"
