#!/usr/bin/env bash
# smoke-check.sh — lightweight container smoke check for Vortex
# Runs without paid APIs, large downloads, or real Telegram tokens.
# Verifies: imports work, config shape, callback/platform routing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Vortex Smoke Check ==="

# 1. Python compile check — all .py files parse
echo "[1/3] Compile check..."
python -m compileall -q "$ROOT" 2>/dev/null || {
    echo "FAIL: compileall"
    exit 1
}
echo "  OK"

# 2. Import check — can we import config without real tokens?
echo "[2/3] Import check..."
python -c "
import sys; sys.path.insert(0, '$ROOT')
from config import BOT_TOKEN, OWNER_TELEGRAM_IDS, DOWNLOAD_DIR
print(f'  BOT_TOKEN present: {bool(BOT_TOKEN)}')
print(f'  DOWNLOAD_DIR: {DOWNLOAD_DIR}')
" || {
    echo "FAIL: config import"
    exit 1
}
echo "  OK"

# 3. Callback/platform routing smoke checks (AST-based, no network)
echo "[3/3] Routing check..."
python "$ROOT/scripts/smoke_check.py" || {
    echo "FAIL: routing check"
    exit 1
}

echo ""
echo "SMOKE_OK — all checks passed."
