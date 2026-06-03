"""LLM summarizer — via LiteLLM proxy (multi-key Gemini, free tiers)."""

import httpx
from config import SUMMARY_MAX_TOKENS

LITELLM_BASE = "http://127.0.0.1:5500/v1"
LITELLM_MODEL = "gemini-flash-lite"  # gemini/gemini-2.5-flash-lite (6 keys)
LITELLM_API_KEY = "fake-key"  # LiteLLM ignores client key


SYSTEM_PROMPT = """Ты — эксперт по анализу видео-контента.

Проанализируй транскрипт и сделай структурированное саммари на русском языке.
Используй ТОЛЬКО Telegram Markdown: **жирный** для заголовков, *курсив* для акцентов.
НЕ используй ## (не работает в Telegram).

Формат ответа:

**Суть**
3-5 предложений о главном — живой язык, без воды.

**Ключевые инсайты**
• Конкретный takeaway 1
• Конкретный takeaway 2
• Конкретный takeaway 3

**Структура**
MM:SS — первая тема
MM:SS — вторая тема
MM:SS — третья тема

**Цитаты**
2-3 запоминающиеся цитаты спикера в прямой речи, в кавычках.

Правила:
- Не пересказывай дословно, выделяй суть и инсайты
- Таймкоды должны соответствовать реальным темам
- Пиши как эксперт, живой, естественный язык
- В Telegram Markdown нет ## — используй **жирный**
""".strip()


def summarize_video(url: str, with_transcript: bool = False, lang: str = "ru-orig,ru,en") -> dict:
    """Full pipeline: fetch subtitles → clean → LLM summary via LiteLLM.

    Returns:
      - success: bool
      - title, duration, uploader, video_id, language
      - summary: str (markdown)
      - transcript: str (if with_transcript=True)
      - error: str
    """
    # 1. Fetch subtitles
    try:
        from core.subtitles_json3 import fetch_transcript
        sub = fetch_transcript(url, languages=lang)
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not sub.get("success"):
        return sub  # propagate error

    transcript = sub["text"]
    title = sub.get("title", "")

    # 2. Send to LLM via LiteLLM proxy
    prompt = SYSTEM_PROMPT + f"\n\nВидео: {title or 'Без названия'}\nДлительность: {sub['duration'] // 60} мин\n\nТранскрипт:\n{transcript[:25000]}"

    try:
        response = httpx.post(
            f"{LITELLM_BASE}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LITELLM_API_KEY}",
            },
            json={
                "model": LITELLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": SUMMARY_MAX_TOKENS,
                "temperature": 0.3,
            },
            timeout=120,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"LiteLLM error {response.status_code}: {response.text[:200]}",
            }

        data = response.json()
        summary_text = data["choices"][0]["message"]["content"]

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
    lines.append(f"📝 *{title}*")
    lines.append("")

    # Add summary body (LLM already produces Telegram-compatible markdown)
    body = summary.get("summary", "")
    if body:
        lines.append(body)
        lines.append("")

    # Add metadata — plain text, no underscores near @username
    dur = summary.get("duration", 0)
    dur_str = f"{dur // 60} мин" if dur else ""
    author = summary.get("uploader", "")
    meta_parts = [p for p in [dur_str, f"@{author}" if author else ""] if p]
    if meta_parts:
        lines.append(" · ".join(meta_parts))

    return "\n".join(lines)
