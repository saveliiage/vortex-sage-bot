"""YouTube subtitle fetcher — via youtube-transcript-api v1.x.
No cookies needed, no browser login required."""


def _get_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    for prefix in ("watch?v=", "youtu.be/", "shorts/", "embed/", "v/"):
        idx = url.find(prefix)
        if idx != -1:
            start = idx + len(prefix)
            vid = url[start:]
            if "&" in vid:
                vid = vid.split("&")[0]
            return vid
    return url


def fetch_subtitles(url: str, languages: list[str] = None) -> dict:
    """Fetch subtitles for a YouTube video.
    
    Returns:
      - success: bool
      - text: str (plain text with [MM:SS] timestamps)
      - raw: list (raw transcript dicts)
      - language: str
      - error: str (if failed)
    """
    languages = languages or ["en", "ru"]
    
    video_id = _get_video_id(url)
    if not video_id or len(video_id) < 8:
        return {"success": False, "error": "Не удалось извлечь видео ID из ссылки"}

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        yt = YouTubeTranscriptApi()
        
        # List available transcripts
        transcript_list = yt.list(video_id)
        
        if not list(transcript_list):
            return {
                "success": False,
                "error": "У видео нет доступных субтитров"
            }
        
        # Fetch with language preference
        entries = yt.fetch(video_id, languages=languages)
        lang_used = entries.language if hasattr(entries, 'language') else languages[0]
        
        # Build text with timestamps
        lines = []
        for entry in entries:
            total_seconds = int(entry.start)
            mm = total_seconds // 60
            ss = total_seconds % 60
            text = entry.text.strip()
            if text:
                lines.append(f"[{mm:02d}:{ss:02d}] {text}")
        
        full_text = "\n".join(lines)
        
        return {
            "success": True,
            "text": full_text,
            "raw": entries,
            "language": lang_used,
            "video_id": video_id,
        }

    except Exception as e:
        error_str = str(e)
        # Check common error types
        if "subtitles are disabled" in error_str.lower():
            return {
                "success": False,
                "error": "У этого видео отключены субтитры"
            }
        elif "not available" in error_str.lower() or "not found" in error_str.lower():
            return {
                "success": False,
                "error": "У видео нет субтитров"
            }
        return {
            "success": False,
            "error": f"Ошибка получения субтитров: {error_str}"
        }
