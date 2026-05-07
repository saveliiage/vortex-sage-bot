"""LLM summarizer — via Google AI Studio (Gemini API)."""

import json
import re
import httpx
from config import GOOGLE_AI_API_KEY, SUMMARY_MODEL, SUMMARY_MAX_TOKENS

SYSTEM_PROMPT = """Ты — AI-ассистент для анализа видео. Твоя задача:

1. Получить расшифровку видео (транскрипт с таймкодами)
2. Сделать краткое саммари (3-5 предложений) — о чём видео
3. Выделить ключевые темы/идеи (списком)
4. Разбить на логические разделы с таймкодами (если видео > 3 минут)

Формат ответа (строго JSON, без markdown-обёртки):
{
  "title": "Название видео (если не указано — придумай сам)",
  "summary": "Краткое саммари на русском, 3-5 предложений",
  "key_points": ["тезис 1", "тезис 2", "тезис 3"],
  "sections": [
    {"time": "00:00", "title": "Вступление", "description": "о чём часть"}
  ]
}"""


def parse_vtt(vtt_text: str) -> str:
    """Convert VTT subtitle content to plain text with timestamps."""
    lines = []
    timestamp_pattern = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})')

    for line in vtt_text.splitlines():
        line = line.strip()
        if not line or line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('language:'):
            continue
        if timestamp_pattern.match(line):
            # Extract start time
            m = timestamp_pattern.match(line)
            ts = m.group(1)  # HH:MM:SS.mmm
            # Convert to MM:SS
            parts = ts.split(':')
            mm = parts[1]
            ss = parts[2].split('.')[0]
            lines.append(f"[{mm}:{ss}]")
        elif line[0].isdigit() and len(line) <= 4:
            # Cue number (1, 2, 3...)
            continue
        else:
            # Actual text
            if lines and lines[-1].startswith('[') and lines[-1].endswith(']'):
                lines[-1] += f" {line}"
            else:
                lines.append(line)

    return "\n".join(lines)


def summarize_from_subtitles(subtitle_text: str, title: str = "", duration: int = 0) -> dict:
    """Send subtitle text to Gemini and get structured summary."""
    if not GOOGLE_AI_API_KEY:
        return {
            "success": False,
            "error": "GOOGLE_AI_API_KEY не указан в .env. Добавь ключ и перезапусти бота."
        }

    user_prompt = f"""Видео: {title or 'Без названия'}
Длительность: {duration} сек

Транскрипт (субтитры):
{subtitle_text[:10000]}"""

    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{SUMMARY_MODEL}:generateContent?key={GOOGLE_AI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_prompt}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": SUMMARY_MAX_TOKENS,
                    "temperature": 0.3,
                },
            },
            timeout=60,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Gemini API error {response.status_code}: {response.text[:200]}"
            }

        data = response.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]

        # Try to parse JSON from response
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            content = content.rsplit("```", 1)[0].strip()

        result = json.loads(content)
        result["success"] = True
        return result

    except json.JSONDecodeError:
        return {
            "success": True,
            "summary": content[:500],
            "key_points": [],
            "sections": [],
            "_raw": content,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def summarize(transcript: str, title: str = "", duration: int = 0) -> dict:
    """Legacy: send Whisper transcript to Gemini. Kept for fallback."""
    return summarize_from_subtitles(transcript, title, duration)


def format_summary_response(summary: dict) -> str:
    """Format summary dict into readable Telegram message."""
    if not summary.get("success"):
        return f"❌ {summary.get('error', 'Неизвестная ошибка')}"

    lines = []
    lines.append(f"📝 **{summary.get('title', 'Саммарайз')}**\n")

    if summary.get("summary"):
        lines.append(f"_{summary['summary']}_\n")

    if summary.get("key_points"):
        lines.append("**Ключевые темы:**")
        for pt in summary["key_points"]:
            lines.append(f"• {pt}")
        lines.append("")

    if summary.get("sections"):
        lines.append("**Разделы:**")
        for sec in summary["sections"]:
            lines.append(f"`{sec.get('time', '??')}` — {sec.get('title', '')}")
            if sec.get("description"):
                lines.append(f"   _{sec['description']}_")

    return "\n".join(lines)
