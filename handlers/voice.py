"""Voice note handler — convert uploaded audio to Telegram voice note."""

import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_TELEGRAM_IDS, DOWNLOAD_DIR
from core.voice import convert_to_voice


def is_allowed(user_id: int) -> bool:
    return user_id in OWNER_TELEGRAM_IDS


async def handle_audio_to_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User uploaded an audio file — convert to OGG/Opus and send as voice note."""
    user = update.effective_user
    if not is_allowed(user.id):
        return

    msg = update.message
    media = msg.audio or msg.voice or (msg.document if msg.document and (msg.document.mime_type or "").startswith("audio/") else None)
    if not media:
        return

    status = await msg.reply_text("⬇️ Скачиваю аудио...")

    fd, src_path = tempfile.mkstemp(suffix=".tmp", dir=DOWNLOAD_DIR)
    os.close(fd)
    try:
        tg_file = await media.get_file()
        await tg_file.download_to_drive(src_path)

        await status.edit_text("🔄 Конвертирую в голосовое...")
        res = convert_to_voice(src_path)
        if not res["success"]:
            await status.edit_text(f"❌ {res.get('error', 'Ошибка конвертации')}")
            return

        voice_path = res["path"]
        size = os.path.getsize(voice_path)
        if size > 50 * 1024 * 1024:
            await status.edit_text(f"⚠️ Голосовое слишком большое ({size // 1024 // 1024} MB), Telegram режет на 50 MB.")
            os.unlink(voice_path)
            return

        duration = getattr(media, "duration", None) or 0

        await status.edit_text("📤 Отправляю голосовое...")
        with open(voice_path, "rb") as f:
            await update.effective_chat.send_voice(
                voice=f,
                duration=int(duration) if duration else None,
            )
        await status.delete()
        os.unlink(voice_path)
    except Exception as e:
        try:
            await status.edit_text(f"❌ {str(e)[:200]}")
        except Exception:
            pass
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)
