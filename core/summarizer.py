"""LLM summarizer — via Google AI Studio (Gemini API).
Uses subtitles_json3.py for fast clean subtitle fetching.
"""

import json
import httpx
from config import GOOGLE_AI_API_KEY, SUMMARY_MODEL, SUMMARY_MAX_TOKENS
from core.subtitles_json3 import fetch_transcript


SYSTEM_PROMPT = """Ты — эксперт по анализу видео-контента.

Проанализируй транскрипт и сделай структурированное саммари на русском языке:

## Суть
3-5 предложений о главном — живой язык, без воды.

## Ключевые инсайты
Bullet list конкретных takeaway, которые можно применить.

## Структура видео
Основные секции с таймкодами [MM:SS]. Не дословно — выдели логические блоки.

## Цитаты
2-3 запоминающиеся цитаты спикера в прямой речи.

Правила:
- Не пересказывай дословно, выделяй суть и инсайты
- Таймкоды должны соответствовать реальным темам
- Пиши как эксперт, а не как AI — живой, естественный язык
"""


def summarize_video(url: str, with_transcript: bool = False, lang: str = "ru-orig,ru,en") -> dict:
    """Full pipeline: fetch subtitles → clean → LLM summary.
    
    Returns:
      - success: bool
      - title, duration, uploader, video_id, language
      - summary: str (markdown)
      - transcript: str (if with_transcript=True)
      - error: str
    """
    # 1. Fetch subtitles
    try:
        sub = fetch_transcript(url, languages=lang)
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not sub.get("success"):
        return sub  # propagate error

    transcript = sub["text"]
    title = sub.get("title", "")

    # 2. Send to LLM
    if not GOOGLE_AI_API_KEY:
        return {
            "success": False,
            "error": "GOOGLE_AI_API_KEY не указан в .env. Добавь ключ и перезапусти бота.",
            "transcript": transcript if with_transcript else None,
        }

    prompt = SYSTEM_PROMPT + f"\n\nВидео: {title or 'Без названия'}\nДлительность: {sub['duration'] // 60} мин\n\nТранскрипт:\n{transcript[:25000]}"

    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{SUMMARY_MODEL}:generateContent?key={GOOGLE_AI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": SUMMARY_MAX_TOKENS,
                    "temperature": 0.3,
                },
            },
            timeout=120,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Gemini API error {response.status_code}: {response.text[:200]}",
            }

        data = response.json()
        summary_text = data["candidates"][0]["content"]["parts"][0]["text"]

        result = {
            "success": True,
            "title": title,
            "duration": sub["duration"],
            "uploader": sub.get("uploader", ""),
            "video_id": sub.get("video_id", ""),
            "language": sub.get("language", ""),
            "summary": summary_text.strip(),
        }
        if with_transcript:
            result["transcript"] = transcript
        return result

    except Exception as e:
        return {"success": False, "error": str(e), "transcript": transcript if with_transcript else None}


def format_summary_response(summary: dict) -> str:
    """Format summary dict into Telegram-friendly markdown message."""
    if not summary.get("success"):
        return f"❌ {summary.get('error', 'Неизвестная ошибка')}"

    lines = []
    title = summary.get('title', 'Саммарайз')
    lines.append(f"📝 **{title}**\n")

    # Add summary body
    body = summary.get("summary", "")
    if body:
        lines.append(body)
        lines.append("")

    # Add metadata footer
    dur = summary.get("duration", 0)
    dur_str = f"{dur // 60} мин" if dur else ""
    author = summary.get("uploader", "")
    meta_parts = [p for p in [dur_str, f"@{author}"] if p]
    if meta_parts:
        lines.append("_" + " · ".join(meta_parts) + "_")

    return "\n".join(lines)
