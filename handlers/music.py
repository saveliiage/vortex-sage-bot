"""Music search handler — /music command."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import OWNER_TELEGRAM_IDS
from core.music import search_youtube_music, download_music, format_track_info


def is_allowed(user_id: int) -> bool:
    return user_id in OWNER_TELEGRAM_IDS


async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /music command — search and download music."""
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("⛔ Этот бот только для личного использования.")
        return

    if not context.args:
        await update.message.reply_text(
            "🎵 **Поиск музыки**\n\n"
            "Использование: `/music <запрос>`\n"
            "Пример: `/music Imagine Dragons Bones`",
            parse_mode="MARKDOWN",
        )
        return

    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Ищу: *{query}*", parse_mode="MARKDOWN")

    tracks = search_youtube_music(query, limit=5)
    
    if not tracks or (len(tracks) == 1 and "error" in tracks[0]):
        await status_msg.edit_text("❌ Ничего не найдено или ошибка поиска.")
        return

    # Save tracks in context for callback
    context.user_data["music_tracks"] = tracks
    
    keyboard = []
    for i, track in enumerate(tracks):
        btn_text = f"{i+1}. {track['title']} — {track['artist']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"music_dl_{i}")])
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="music_cancel")])
    
    await status_msg.edit_text(
        f"🎵 Найдено по запросу: *{query}*\n\nВыбери трек:",
        parse_mode="MARKDOWN",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_music_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle music download callback."""
    query = update.callback_query
    await query.answer()
    
    tracks = context.user_data.get("music_tracks", [])
    if not tracks:
        await query.edit_message_text("⚠️ Результаты поиска устарели. Отправь /music ещё раз.")
        return

    data = query.data
    if data == "music_cancel":
        await query.edit_message_text("🎵 Поиск отменён.")
        context.user_data.pop("music_tracks", None)
        return

    # Extract index from music_dl_0, music_dl_1, etc.
    try:
        idx = int(data.replace("music_dl_", ""))
    except ValueError:
        await query.edit_message_text("⚠️ Ошибка.")
        return

    if idx >= len(tracks):
        await query.edit_message_text("⚠️ Трек не найден.")
        return

    track = tracks[idx]
    track_text = format_track_info(track)
    
    await query.edit_message_text(f"⬇️ Скачиваю:\n\n{track_text}", parse_mode="MARKDOWN")

    result = download_music(
        video_id=track["video_id"],
        title=track["title"],
        artist=track["artist"],
    )

    if not result["success"]:
        await query.edit_message_text(f"❌ Ошибка скачивания:\n{result['error']}")
        return

    # Send the MP3 file
    await query.edit_message_text("📤 Отправляю файл...")
    
    with open(result["path"], "rb") as f:
        await update.effective_chat.send_audio(
            audio=f,
            title=track["title"],
            performer=track["artist"],
        )
    
    # Cleanup
    try:
        import os
        os.unlink(result["path"])
    except OSError:
        pass
    
    context.user_data.pop("music_tracks", None)
