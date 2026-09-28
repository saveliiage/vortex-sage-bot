"""Vortex configuration — load from .env, single source of truth."""

import os
import shutil
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN=os.getenv("BOT_TOKEN", "")


def _parse_ids(raw: str) -> set[int]:
    """Parse comma/semicolon-separated Telegram IDs into a set."""
    return {
        int(x.strip())
        for x in (raw or "").replace(";", ",").split(",")
        if x.strip().isdigit() and int(x.strip())
    }


# Support both single ID and comma-separated list in ALLOWED_USER_ID
ALLOWED_USER_IDS = _parse_ids(os.getenv("ALLOWED_USER_ID", "0"))
# Keep backwards-compat single value (first ID or 0)
ALLOWED_USER_ID = min(ALLOWED_USER_IDS) if ALLOWED_USER_IDS else 0

# Owner IDs — defaults to ALLOWED_USER_IDS if not set
OWNER_TELEGRAM_IDS = _parse_ids(os.getenv("OWNER_TELEGRAM_IDS", "")) or ALLOWED_USER_IDS

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/app/downloads")

# Database — Postgres in production, SQLite fallback for local dev
VORTEX_DATABASE_URL = os.getenv("VORTEX_DATABASE_URL", "")
# Legacy SQLite path — kept for backwards-compat of old tests that still import it.
VORTEX_DB_PATH = os.getenv("VORTEX_DB_PATH", "/app/vortex.db")

OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY", "")
APIFY_TOKEN=os.getenv("APIFY_TOKEN", "")

# Paths — vault is optional, only used if it exists
VAULT_PATH = os.getenv("VAULT_PATH", "/app/vault")
TRANSCRIPTS_DIR = os.path.join(VAULT_PATH, "🧠 Knowledge", "Transcripts")

# Whisper
WHISPER_MODEL = "base"  # base | small | medium

# LLM — Google AI Studio (Gemini) — direct API, no LiteLLM proxy needed
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gemini-2.0-flash")
SUMMARY_MAX_TOKENS = int(os.getenv("SUMMARY_MAX_TOKENS", "2000"))

# Telegram — local Bot API server (2 GB file limit) or cloud (50 MB)
# When using local Bot API, python-telegram-bot needs api_id/api_hash and base_url override
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_BOT_API_URL = os.getenv("TELEGRAM_BOT_API_URL", "")  # e.g. http://172.17.0.2:8081
# File size limit: 2 GB with local Bot API, 50 MB with cloud
TELEGRAM_FILE_SIZE = 2 * 1024 * 1024 * 1024 if TELEGRAM_BOT_API_URL else 50 * 1024 * 1024

# yt-dlp binary — auto-detect, fallback to /opt/vortex/venv/bin/yt-dlp for legacy installs
YT_DLP_BIN = shutil.which("yt-dlp") or os.getenv("YT_DLP_BIN", "/opt/vortex/venv/bin/yt-dlp")

# YouTube cookies — Netscape format file (optional). If set and exists, used by yt-dlp.
# If empty, yt-dlp runs without cookies (may fail on some restricted videos).
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "")

# Build yt-dlp cookies args dynamically
def _build_yt_cookies_args() -> list:
    """Build yt-dlp cookie arguments based on config."""
    args = []
    if YT_COOKIES_FILE and os.path.exists(YT_COOKIES_FILE):
        args += ["--cookies", YT_COOKIES_FILE]
    # --remote-components is needed for some yt-dlp versions
    args += ["--remote-components", "ejs:github"]
    return args

YT_COOKIES_ARGS = _build_yt_cookies_args()

# Ensure dirs exist
for _d in (DOWNLOAD_DIR, TRANSCRIPTS_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except (OSError, PermissionError):
        pass
