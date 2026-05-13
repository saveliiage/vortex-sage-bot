"""Vortex configuration — load from .env, single source of truth."""

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN=os.getenv("BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/opt/vortex/downloads")
OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY", "")
APIFY_TOKEN=os.getenv("APIFY_TOKEN", "")

# Paths
VAULT_PATH = "/opt/obsidian/vault"
TRANSCRIPTS_DIR = os.path.join(VAULT_PATH, "🧠 Knowledge", "Transcripts")

# Whisper
WHISPER_MODEL = "base"  # base | small | medium

# LLM — Google AI Studio (Gemini)
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gemini-2.0-flash")
SUMMARY_MAX_TOKENS = 1024

# Telegram limits
TELEGRAM_FILE_SIZE = 50 * 1024 * 1024  # 50 MB (для Premium — 2GB, пока не трогаем)

# Ensure dirs exist
# YouTube cookies (Netscape format, from Sava's browser)
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "/opt/vortex/cookies/youtube.txt")

try:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
except (OSError, PermissionError):
    pass
try:
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
except (OSError, PermissionError):
    pass
