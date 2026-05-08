"""Download handlers — process media links and actions with progress bars."""

import os
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from core.downloader import download_video, download_audio, get_info, download_thumbnail
from core.circle import convert_to_circle
from core.progress import run_ytdlp, run_ffmpeg_with_progress
from config import TELEGRAM_FILE_SIZE, DOWNLOAD_DIR

YT_DLP = "/opt/vortex/venv/bin/yt-dlp"
YT_COOKIES_TXT = "/opt/vortex/cookies/youtube.txt"
_YT_COOKIES_ARG = [
    "--cookies", YT_COOKIES_TXT,
    "--remote-components", "ejs:github",
] if os.path.exists(YT_COOKIES_TXT) else [
    "--remote-components", "ejs:github",
]


# ── Error helpers ────────────────────────────────────────────────────────────

_ERROR_TEMPLATES = {
    "yt-dlp failed": "❌ yt-dlp не смог скачать файл. Возможно видео удалено или ссылка битая.",
    "yt-dlp не вернул путь к файлу": "❌ Что-то пошло при скачивании — попробуй ещё раз.",
    "ffmpeg": "❌ Ошибка конвертации видео. Формат может быть неподдерживаемым.",
    "HTTP Error 403": "❌ Доступ запрещён (403). Возможно видео приватное или регион заблокирован.",
    "HTTP Error 404": "❌ Видео не найдено (404). Проверь ссылку.",
    "HTTP Error 410": "❌ Видео удалено (410).",
    "Private video": "❌ Это приватное видео. Открытый доступ не даёт скачать.",
    "copyright": "❌ Видео заблокировано за нарушение авторских прав.",
    "Video unavailable": "❌ Видео недоступно.",
    "Sign in to confirm": "❌ YouTube требует авторизацию. Возможно, нужны свежие куки.",
    "No video formats found": "❌ Не удалось найти видео в подходящем формате.",
    "APIFY_TOKEN": "❌ Apify-токен не настроен. Напиши Дэдалу.",
    "is not a valid URL": "❌ Это не похоже на ссылку. Проверь формат.",
    "Apify пустой результат": "❌ TikTok/Instagram не вернул данные. Возможно пост приватный.",
    "Apify запрос упал": "❌ Сервис скачивания временно недоступен. Попробуй позже.",
    "Не удалось скачать видео": "❌ Не удалось скачать видео с этой платформы.",
    "Не удалось скачать аудио": "❌ Не удалось извлечь аудио.",
}


def humanize_error(raw: str) -> str:
    """Turn raw error string into human-readable Russian message."""
    if not raw:
        return "❌ Неизвестная ошибка."
    for fragment, friendly in _ERROR_TEMPLATES.items():
        if fragment.lower() in raw.lower():
            return friendly
    # Fallback — truncate technical stuff
    clean = raw.strip()
    if len(clean) > 150:
        clean = clean[:147] + "..."
    return f"❌ {clean}"


# ── Status updater helper ────────────────────────────────────────────────────


async def _edit(msg, text: str, parse_mode=None):
    """Safely edit a message (catch errors if msg was deleted)."""
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except Exception:
        pass


async def _send(context, chat_id, text: str, parse_mode=None):
    """Send a new message safely."""
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception:
        return None


# ── Handlers ─────────────────────────────────────────────────────────────────


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: user sent a link. Show action menu."""
    url = update.message.text.strip()
    from handlers.menu import media_action_keyboard
    await update.message.reply_text(
        "📎 Что сделать с этим видео?",
        reply_markup=media_action_keyboard(url, context),
    )


async def _ytdlp_download_with_progress(
    url: str,
    format_spec: str,
    progress_callback,
    label: str = "⬇️ Скачиваю",
) -> dict:
    """Download using async yt-dlp with progress. Returns {success, path}."""
    output_template = os.path.join(DOWNLOAD_DIR, "%(title).100s_%(epoch)s.%(ext)s")
    result = await run_ytdlp(
        [YT_DLP, "--no-playlist", "--no-warnings"]
        + _YT_COOKIES_ARG
        + ["-f", format_spec, "-o", output_template, "--print", "after_move:filepath", url],
        progress_callback=progress_callback,
        label=label,
    )
    if not result["success"]:
        return result
    path = result["output"].splitlines()[-1].strip() if result["output"] else ""
    if not path or not os.path.exists(path):
        return {"success": False, "error": "yt-dlp не вернул путь к файлу"}
    return {"success": True, "path": path}


async def handle_download_video(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download video and send as file, with progress bar."""
    query = update.callback_query
    status = await query.edit_message_text("⬇️ Скачиваю видео...")

    # Use the platform router here, not raw yt-dlp:
    # Instagram needs embed/Apify fallback, TikTok needs Apify.
    result = download_video(url)

    if not result["success"]:
        await _edit(status, humanize_error(result.get("error", "")))
        return

    filepath = result["path"]
    filesize = os.path.getsize(filepath)

    if filesize > TELEGRAM_FILE_SIZE:
        await _edit(status,
            f"⚠️ Видео слишком большое ({filesize // 1024 // 1024} MB). "
            f"Лимит Telegram — 50 MB. Попробуй скачать аудио."
        )
        os.unlink(filepath)
        return

    await _edit(status, "📤 Отправляю видео...")
    with open(filepath, "rb") as f:
        await update.effective_chat.send_video(
            video=f,
            caption=f"✅ Готово | {os.path.basename(filepath)}",
            supports_streaming=True,
        )

    os.unlink(filepath)


async def handle_download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download audio and send as file, with progress bar."""
    query = update.callback_query
    status = await query.edit_message_text("⬇️ Скачиваю аудио...")

    result = download_audio(url)

    if not result["success"]:
        await _edit(status, humanize_error(result.get("error", "")))
        return

    path = result.get("path", "")
    if not path or not os.path.exists(path):
        await _edit(status, "❌ Аудио скачалось, но файл не найден.")
        return

    filepath = path
    filesize = os.path.getsize(filepath)

    if filesize > TELEGRAM_FILE_SIZE:
        await _edit(status,
            f"⚠️ Аудио слишком большое ({filesize // 1024 // 1024} MB)."
        )
        os.unlink(filepath)
        return

    await _edit(status, "📤 Отправляю аудио...")
    with open(filepath, "rb") as f:
        await update.effective_chat.send_audio(
            audio=f,
            caption=f"✅ Готово | {os.path.basename(filepath)}",
        )

    os.unlink(filepath)


async def handle_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download and send thumbnail."""
    query = update.callback_query
    await query.edit_message_text("🖼 Скачиваю превью...")

    result = download_thumbnail(url)
    if not result["success"]:
        await query.edit_message_text(humanize_error(result.get("error", "")))
        return

    filepath = result["path"]
    with open(filepath, "rb") as f:
        await update.effective_chat.send_photo(photo=f)

    os.unlink(filepath)


async def handle_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Show video metadata."""
    query = update.callback_query
    await query.edit_message_text("ℹ️ Получаю информацию...")

    result = get_info(url)
    if not result["success"]:
        await query.edit_message_text(humanize_error(result.get("error", "")))
        return

    duration = result.get("duration", 0)
    mins, secs = divmod(int(duration), 60)
    hours, mins = divmod(mins, 60)
    if hours:
        duration_str = f"{hours}ч {mins}м {secs}с"
    else:
        duration_str = f"{mins}м {secs}с"

    filesize = result.get("filesize", 0)
    size_str = f"{filesize // 1024 // 1024} MB" if filesize else "неизвестно"

    info_text = (
        f"📹 **{result['title']}**\n\n"
        f"⏱ Длительность: {duration_str}\n"
        f"📦 Размер: ~{size_str}\n"
        f"🌐 Платформа: {result['platform']}\n"
        f"🔗 [Открыть]({result['webpage_url']})"
    )

    await query.edit_message_text(
        info_text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def handle_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Full pipeline: download subtitles → LLM summary → save to vault."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    status = await query.edit_message_text("📥 Получаю информацию о видео...")

    # Step 1: get video info
    info = get_info(url)
    if not info["success"]:
        await _edit(status, humanize_error(info.get("error", "")))
        return

    title = info.get("title", "Untitled")
    platform = info.get("platform", "unknown")
    duration = info.get("duration", 0)

    await _edit(status, f"📝 Скачиваю субтитры: **{title}**", parse_mode=ParseMode.MARKDOWN)

    # Step 2: download auto-subtitles via yt-dlp
    sub_dir = os.path.join(DOWNLOAD_DIR, "sub_tmp")
    os.makedirs(sub_dir, exist_ok=True)
    sub_path = os.path.join(sub_dir, f"sub_{os.path.basename(url).split('=')[-1] or 'video'}")

    async def _sub_progress(text):
        await _edit(status, text)

    result = await run_ytdlp(
        [YT_DLP, "--no-playlist", "--no-warnings"]
        + _YT_COOKIES_ARG
        + ["--skip-download", "--write-auto-sub", "--sub-lang", "en,ru",
           "--sub-format", "vtt",
           "-o", sub_path, url],
        progress_callback=_sub_progress,
        label="📝 Скачиваю субтитры",
    )

    if not result["success"]:
        await _edit(status, humanize_error(result.get("error", "")))
        return

    # Find downloaded .vtt file
    import glob
    vtt_files = glob.glob(f"{sub_path}*.vtt")
    if not vtt_files:
        await _edit(status,
            f"❌ У видео **{title}** нет субтитров.\n\n"
            "Попробуй другое видео — нужны те, где есть авто-субтитры (значок CC)."
        )
        return

    # Pick first vtt (en preferred, ru fallback)
    vtt_path = sorted(vtt_files)[0]

    try:
        # Step 3: parse VTT
        from core.summarizer import parse_vtt, summarize_from_subtitles, format_summary_response

        with open(vtt_path, "r", encoding="utf-8") as f:
            vtt_text = f.read()

        subtitle_text = parse_vtt(vtt_text)

        if len(subtitle_text.strip()) < 50:
            await _edit(status,
                f"❌ Субтитры слишком короткие или пустые для **{title}**."
            )
            return

        # Step 4: summarize via LLM
        await _edit(status, "🧠 Анализирую через AI...")

        summary_result = summarize_from_subtitles(
            subtitle_text=subtitle_text,
            title=title,
            duration=duration,
        )

        # Step 5: send result
        response_text = format_summary_response(summary_result)
        full_message = f"📝 **{title}**\n\n{response_text}"

        if len(full_message) > 4000:
            full_message = full_message[:4000] + "\n\n... (обрезано)"

        await _edit(status, full_message, parse_mode=ParseMode.MARKDOWN)

        # Step 6: save full transcript for vault
        from core.vault import save_transcript
        vault_path = save_transcript(
            title=title,
            source_url=url,
            platform=platform,
            duration=duration,
            full_text=subtitle_text,
            summary_data=summary_result,
        )

        # Step 7: ask to save to Obsidian
        from handlers.menu import save_to_vault_keyboard
        await _send(context, chat_id,
            f"💾 Сохранить транскрипт в Obsidian vault?\n`{vault_path}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text="💾 Сохранить транскрипт в Obsidian vault?",
            reply_markup=save_to_vault_keyboard(title, vault_path, context),
        )

    except Exception as e:
        err_msg = str(e)[:200]
        await _edit(status, f"❌ Ошибка при саммарайзе: {err_msg}")
    finally:
        # Clean up temp files
        import glob as g
        for f in g.glob(f"{sub_path}*"):
            try:
                os.unlink(f)
            except OSError:
                pass


async def handle_circle(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download video → convert to circle (640x640 video note) → send."""
    query = update.callback_query
    status = await query.edit_message_text("⬇️ Скачиваю видео для кружочка...")

    # Get duration
    info = get_info(url)
    duration = info.get("duration", 60) if info.get("success") else 60

    # Download through platform router so Instagram uses embed/Apify instead of raw yt-dlp.
    result = download_video(url)

    if not result["success"]:
        await _edit(status, humanize_error(result.get("error", "")))
        return

    video_path = result["path"]

    try:
        async def _conv_progress(text):
            await _edit(status, text)

        await _edit(status, "🔄 Конвертирую в кружочек...")

        # Use async ffmpeg with progress
        circle_result = await run_ffmpeg_with_progress(
            input_path=video_path,
            output_path=os.path.join(DOWNLOAD_DIR, f"circle_{os.path.basename(video_path)}"),
            filters="scale=640:640:force_original_aspect_ratio=increase,crop=640:640",
            duration_sec=min(duration, 60),
            extra_args=[
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-t", "60",
            ],
            progress_callback=_conv_progress,
            label="🔄 Конвертирую",
        )

        if not circle_result["success"]:
            await _edit(status, f"❌ Ошибка конвертации: {circle_result.get('error', 'неизвестная')}")
            return

        circle_path = circle_result["path"]
        filesize = os.path.getsize(circle_path)

        if filesize > TELEGRAM_FILE_SIZE:
            await _edit(status,
                f"⚠️ Кружочек слишком большой ({filesize // 1024 // 1024} MB)."
            )
            os.unlink(circle_path)
            return

        await _edit(status, "📤 Отправляю кружочек...")
        with open(circle_path, "rb") as f:
            await update.effective_chat.send_video_note(
                video_note=f,
                duration=min(duration, 60),
            )

        os.unlink(circle_path)
        # Delete the status message once sent
        try:
            await status.delete()
        except Exception:
            pass

    except Exception as e:
        await _edit(status, f"❌ Ошибка: {str(e)[:200]}")
    finally:
        if os.path.exists(video_path):
            os.unlink(video_path)