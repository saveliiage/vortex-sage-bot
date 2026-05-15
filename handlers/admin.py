"""Admin Telegram commands for Vortex."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_TELEGRAM_IDS, VORTEX_DB_PATH
from core.access import AccessStore, VALID_PLANS


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


def _store() -> AccessStore:
    return AccessStore(VORTEX_DB_PATH, owner_ids=OWNER_TELEGRAM_IDS)


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
