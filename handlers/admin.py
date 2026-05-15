"""Admin Telegram commands for Vortex."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_TELEGRAM_IDS, VORTEX_DATABASE_URL
from core.access_pg import AccessStore, VALID_PLANS
from core.db import create_db_engine


def _resolve_database_url() -> str:
    """Return the database URL for the access store.

    Prefers VORTEX_DATABASE_URL (Postgres in production). Falls back to
    VORTEX_DB_PATH (SQLite) for legacy/local dev. If neither is set,
    uses a local SQLite file for development.
    """
    from config import VORTEX_DB_PATH
    if VORTEX_DATABASE_URL:
        return VORTEX_DATABASE_URL
    if VORTEX_DB_PATH:
        return f"sqlite:///{VORTEX_DB_PATH}"
    return "sqlite:///vortex.db"


_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_db_engine(_resolve_database_url())
    return _engine


def _store() -> AccessStore:
    return AccessStore(engine=_get_engine(), owner_ids=OWNER_TELEGRAM_IDS)


def parse_admin_plan_args(args: list[str]) -> dict[str, object]:
    """Parse `/admin_plan <telegram_id> <plan> [duration]` arguments."""
    if len(args) not in (2, 3):
        raise ValueError("usage: /admin_plan <telegram_id> <owner|free|pro|creator|blocked> [30d|12h|forever]")
    try:
        telegram_id = int(args[0])
    except ValueError as exc:
        raise ValueError("telegram_id must be an integer") from exc
    plan = args[1].strip().lower()
    if plan not in VALID_PLANS:
        raise ValueError(f"plan must be one of: {', '.join(sorted(VALID_PLANS))}")
    duration = args[2].strip().lower() if len(args) == 3 else None
    return {"telegram_id": telegram_id, "plan": plan, "duration": duration}


async def admin_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only command to set a user's plan."""
    actor = update.effective_user
    msg = update.effective_message
    if not actor or actor.id not in OWNER_TELEGRAM_IDS:
        if msg:
            await msg.reply_text("⛔ Только owner может менять планы.")
        return

    try:
        parsed = parse_admin_plan_args(list(context.args or []))
        updated = _store().set_plan(
            telegram_id=int(parsed["telegram_id"]),
            plan=str(parsed["plan"]),
            duration=parsed["duration"] if parsed["duration"] is None else str(parsed["duration"]),
            actor_id=actor.id,
        )
    except Exception as exc:
        if msg:
            await msg.reply_text(f"❌ {exc}")
        return

    expires = updated.get("plan_expires_at") or "без срока"
    if msg:
        await msg.reply_text(
            f"✅ План обновлён: `{updated['telegram_id']}` → **{updated['plan']}**\n"
            f"⏳ Истекает: `{expires}`",
            parse_mode="MARKDOWN",
        )
