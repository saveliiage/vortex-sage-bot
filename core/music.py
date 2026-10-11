"""Music search and download via ytmusicapi + yt-dlp."""

import os
import re

from config import DOWNLOAD_DIR
from core import ytdlp


def search_youtube_music(query: str, limit: int = 5) -> list:
    """Search for music on YouTube using ytmusicapi."""
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        results = yt.search(query, filter="songs", limit=limit)
        
        tracks = []
        for r in results:
            if r.get("resultType") != "song":
                continue
            video_id = r.get("videoId", "")
            title = r.get("title", "")
            artist = ", ".join(a.get("name", "") for a in r.get("artists", [])) if r.get("artists") else ""
            duration = r.get("duration", "")
            album = r.get("album", {}).get("name", "") if r.get("album") else ""
            thumbnail = r.get("thumbnails", [{}])[-1].get("url", "")
            
            tracks.append({
                "video_id": video_id,
                "url": f"https://music.youtube.com/watch?v={video_id}",
                "title": title,
                "artist": artist,
                "duration": duration,
                "album": album,
                "thumbnail": thumbnail,
            })
        return tracks
    except Exception as e:
        return [{"error": str(e)}]


def download_music(video_id: str, title: str = "", artist: str = "") -> dict:
    """Download music as MP3 with metadata tags."""
    # Clean filename
    safe_title = re.sub(r'[^\w\s\-\.]', '', title or "unknown")[:80]
    safe_artist = re.sub(r'[^\w\s\-\.]', '', artist or "unknown")[:60]
    filename = f"{safe_artist} - {safe_title}.mp3"
    output_path = os.path.join(DOWNLOAD_DIR, filename)

    args = [
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--add-metadata",
        "--embed-thumbnail",
        "-o", output_path,
        "--print", "after_move:filepath",
        f"https://music.youtube.com/watch?v={video_id}",
    ]

    # Anonymous first, the cookie jar only as a retry — a stale jar must not break the track.
    result = ytdlp.run(args, want_path=True, timeout=300)
    if not result["success"]:
        return {"success": False, "error": result.get("error", "yt-dlp failed")}

    return {"success": True, "path": result["path"], "title": f"{safe_artist} - {safe_title}"}


def format_track_info(track: dict) -> str:
    """Format track info for Telegram message."""
    duration = track.get("duration", "")
    album = track.get("album", "")
    text = f"🎵 **{track['title']}**\n"
    text += f"👤 {track['artist']}"
    if album:
        text += f"\n💿 {album}"
    if duration:
        text += f"\n⏱ {duration}"
    return text
