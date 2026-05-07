"""Inline menus for Vortex bot — using context.user_data to avoid long callback_data."""

import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from telegram import Update


ACTIONS = {
    "dl_video": "🎬 Скачать видео",
    "dl_audio": "🎵 Скачать аудио",
    "summarize": "📝 Сделать саммарайз",
    "circle": "🔵 Кружочек",
    "thumbnail": "🖼 Превью",
    "info": "ℹ️ Инфо",
}


def media_action_keyboard(url: str, context: CallbackContext = None) -> InlineKeyboardMarkup:
    """Show action picker. URL stored in context.user_data, callback_data is just action name."""
    if context:
        context.user_data["vortex_url"] = url

    buttons = [
        [
            InlineKeyboardButton(ACTIONS["dl_video"], callback_data="dl_video"),
            InlineKeyboardButton(ACTIONS["dl_audio"], callback_data="dl_audio"),
        ],
        [
            InlineKeyboardButton(ACTIONS["summarize"], callback_data="summarize"),
            InlineKeyboardButton(ACTIONS["circle"], callback_data="circle"),
        ],
        [
            InlineKeyboardButton(ACTIONS["thumbnail"], callback_data="thumbnail"),
            InlineKeyboardButton(ACTIONS["info"], callback_data="info"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def save_to_vault_keyboard(video_title: str, transcript_path: str, context: CallbackContext = None) -> InlineKeyboardMarkup:
    """Ask if user wants to save transcript to Obsidian vault."""
    if context:
        context.user_data["vault_title"] = video_title
        context.user_data["vault_path"] = transcript_path

    buttons = [
        [
            InlineKeyboardButton("✅ Да, сохранить", callback_data="save_yes"),
            InlineKeyboardButton("❌ Нет", callback_data="save_no"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def get_url(context: CallbackContext) -> str:
    """Get stored URL from context."""
    return context.user_data.get("vortex_url", "")


async def handle_callback(update: Update, context: CallbackContext):
    """Route callback queries to appropriate handlers."""
    query = update.callback_query
    await query.answer()

    if not query.data:
        return

    action = query.data

    if action == "save_yes":
        transcript_path = context.user_data.get("vault_path", "")
        video_title = context.user_data.get("vault_title", "Untitled")

        if not transcript_path or not os.path.exists(transcript_path):
            await query.edit_message_text("❌ Файл транскрипта не найден.")
            return

        from core.vault import git_push
        await query.edit_message_text(f"💾 Сохраняю «{video_title}» в Obsidian...")

        result = git_push(transcript_path)
        if result.get("success"):
            await query.edit_message_text(
                f"✅ Транскрипт сохранён в Obsidian vault!\n"
                f"📂 `{transcript_path}`",
                parse_mode="MARKDOWN",
            )
        else:
            await query.edit_message_text(
                f"⚠️ Файл сохранён локально, но git push не удался:\n"
                f"`{result.get('error', result.get('output', '?'))[:200]}`",
                parse_mode="MARKDOWN",
            )

    elif action == "save_no":
        await query.edit_message_text("Ок, не сохраняю.")

    elif action in ACTIONS:
        url = get_url(context)
        if not url:
            await query.edit_message_text("❌ Ссылка не найдена. Отправь ссылку заново.")
            return

        if action == "dl_video":
            from handlers.download import handle_download_video
            await handle_download_video(update, context, url)
        elif action == "dl_audio":
            from handlers.download import handle_download_audio
            await handle_download_audio(update, context, url)
        elif action == "summarize":
            from handlers.download import handle_summarize
            await handle_summarize(update, context, url)
        elif action == "circle":
            from handlers.download import handle_circle
            await handle_circle(update, context, url)
        elif action == "thumbnail":
            from handlers.download import handle_thumbnail
            await handle_thumbnail(update, context, url)
        elif action == "info":
            from handlers.download import handle_info
            await handle_info(update, context, url)
    else:
        await query.edit_message_text("Неизвестная команда.")