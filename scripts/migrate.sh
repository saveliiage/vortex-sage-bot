#!/usr/bin/env bash
# migrate.sh — run Alembic migrations against VORTEX_DATABASE_URL
# Usage: ./scripts/migrate.sh [upgrade|downgrade|stamp|current|history]
# Default: upgrade head
set -euo pipefail

cd "$(dirname "$0")/.."

ACTION="${1:-upgrade}"
EXTRA="${2:-head}"

if [ -z "${VORTEX_DATABASE_URL:-}" ]; then
    echo "Error: VORTEX_DATABASE_URL not set"
    echo "Example: VORTEX_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/vortex"
    echo "         VORTEX_DATABASE_URL=sqlite:///vortex.db  (dev only)"
    exit 1
fi

echo "→ Running: alembic $ACTION $EXTRA"
echo "→ DB: ${VORTEX_DATABASE_URL//:*@/:****@}"
alembic "$ACTION" "$EXTRA"
