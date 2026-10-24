"""Vortex Bot — entry point."""

import logging
import re
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import os
import tempfile

from config import BOT_TOKEN, OWNER_TELEGRAM_IDS, DOWNLOAD_DIR, ALLOWED_USER_IDS
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_API_URL
from handlers.menu import handle_callback
from handlers.download import handle_link, humanize_error, handle_quality_choice
from handlers.music import search_music, handle_music_download
from handlers.voice import handle_audio_to_voice
from handlers.admin import admin_plan
from core.downloader import clean_downloads
from core.circle import convert_to_circle

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# URL pattern — detect links in messages
URL_PATTERN = re.compile(
    r"https?://[^\s]+", re.IGNORECASE
)


def is_allowed(user_id: int) -> bool:
    """Check if user is an owner or allowed user (from OWNER_TELEGRAM_IDS / ALLOWED_USER_IDS)."""
    return user_id in OWNER_TELEGRAM_IDS or user_id in ALLOWED_USER_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("⛔ Этот бот только для личного использования.")
        return

    await update.message.reply_text(
        "🌀 **Vortex** — твой медиа-хаб.\n\n"
        "📎 **Скачивание:** отправь ссылку на видео или пост с фото с YouTube, TikTok, Instagram,\n"
        "Pinterest, Twitter/X, Vimeo или любого другого сайта. Карусели из инсты приходят альбомом.\n\n"
        "🎵 **Музыка:** просто напиши название трека — найду на YouTube Music\n\n"
        "Я предложу варианты:\n"
        "⬇️ Скачать\n"
        "🎵 Скачать аудио\n"
        "📝 Сделать саммарайз\n"
        "🔵 Кружочек\n"
        "🖼 Превью\n"
        "ℹ️ Инфо\n\n"
        "Поехали 👇",
        parse_mode="MARKDOWN",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages — detect URLs and route."""
    user = update.effective_user
    if not is_allowed(user.id):
        return  # silently ignore

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Check if it's a URL
    if URL_PATTERN.match(text):
        await handle_link(update, context)
    else:
        # Plain text — ask what to do, do NOT auto-search
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        context.user_data["vortex_text_query"] = text
        await update.message.reply_text(
            f"📝 «{text[:100]}»\n\nЧто сделать?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 Найти музыку", callback_data="text_music")],
                [InlineKeyboardButton("❌ Ничего", callback_data="text_cancel")],
            ]),
        )


async def handle_text_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text-menu callbacks: text_music / text_cancel."""
    query = update.callback_query
    await query.answer()
    if not query.data:
        return

    text = context.user_data.get("vortex_text_query", "")
    context.user_data.pop("vortex_text_query", None)

    if query.data == "text_music" and text:
        from handlers.music import run_music_search
        await query.edit_message_text(f"🎵 Ищу: *{text}*", parse_mode="MARKDOWN")
        await run_music_search(update, context, text)
    else:
        await query.edit_message_text("Ок 👌")


async def handle_video_to_circle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User uploaded a video/animation/document — convert to Telegram video note (circle)."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    msg = update.message
    media = msg.video or msg.animation or (msg.document if msg.document and (msg.document.mime_type or "").startswith("video/") else None)
    if not media:
        return

    status = await msg.reply_text("⬇️ Скачиваю видео...")

    fd, src_path = tempfile.mkstemp(suffix=".mp4", dir=DOWNLOAD_DIR)
    os.close(fd)
    try:
        tg_file = await media.get_file()
        await tg_file.download_to_drive(src_path)

        await status.edit_text("🔄 Конвертирую в кружочек...")
        duration = getattr(media, "duration", None) or 60
        res = convert_to_circle(src_path, duration=duration)
        if not res["success"]:
            await status.edit_text(humanize_error(res.get('error', '?')))
            return

        circle_path = res["path"]
        size = os.path.getsize(circle_path)
        if size > 2 * 1024 * 1024 * 1024:
            await status.edit_text(f"⚠️ Кружочек слишком большой ({size // 1024 // 1024} MB).")
            os.unlink(circle_path)
            return

        await status.edit_text("📤 Отправляю кружочек...")
        with open(circle_path, "rb") as f:
            await update.effective_chat.send_video_note(
                video_note=f,
                duration=min(duration, 60),
            )
        await status.delete()
        os.unlink(circle_path)
    except Exception as e:
        try:
            await status.edit_text(f"❌ {str(e)[:200]}")
        except Exception:
            pass
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)


def main():
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set in .env")
        return
    if not OWNER_TELEGRAM_IDS:
        logger.error("OWNER_TELEGRAM_IDS not set in .env")
        return

    async def post_init(app):
        """Register command hints (autocomplete menu when user types /)."""
        from telegram import BotCommand
        await app.bot.set_my_commands([
            BotCommand("start", "Как пользоваться ботом"),
            BotCommand("music", "Найти трек (или просто напиши название)"),
            BotCommand("admin_plan", "Изменить план пользователя"),
        ])

    app = Application.builder().token(BOT_TOKEN)
    app = app.post_init(post_init)

    # Connect to local Bot API server if configured (enables 2 GB file uploads)
    if TELEGRAM_BOT_API_URL:
        app = app.base_url(f"{TELEGRAM_BOT_API_URL}/bot")
        app = app.base_file_url(f"{TELEGRAM_BOT_API_URL}/file/bot")
        logger.info(f"Using local Bot API: {TELEGRAM_BOT_API_URL}")

    app = app.build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("music", search_music))
    app.add_handler(CommandHandler("admin_plan", admin_plan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.ANIMATION | filters.Document.VIDEO,
        handle_video_to_circle,
    ))
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.Document.AUDIO,
        handle_audio_to_voice,
    ))
    app.add_handler(CallbackQueryHandler(handle_music_download, pattern=r"^music_"))
    app.add_handler(CallbackQueryHandler(
        handle_text_action,
        pattern=r"^text_(music|cancel)$",
    ))
    app.add_handler(CallbackQueryHandler(
        handle_quality_choice,
        pattern=r"^q_",
    ))
    app.add_handler(CallbackQueryHandler(
        handle_callback,
        pattern=r"^(dl_video|dl_audio|summarize|circle|thumbnail|info)$",
    ))

    # Periodic cleanup of downloads/ — files older than 1h, every 30 min
    async def _cleanup_job(context: ContextTypes.DEFAULT_TYPE):
        try:
            clean_downloads(hours=1)
        except Exception as e:
            logger.warning(f"cleanup failed: {e}")
    app.job_queue.run_repeating(_cleanup_job, interval=1800, first=60)

    logger.info(f"Vortex bot started. Owners: {OWNER_TELEGRAM_IDS}")
    print("🌀 Vortex bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()