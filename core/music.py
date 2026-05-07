"""Music search and download via ytmusicapi + yt-dlp."""

import os
import re
import json
import subprocess
from pathlib import Path

from config import DOWNLOAD_DIR, YT_COOKIES_FILE

YT_DLP = "/opt/vortex/venv/bin/yt-dlp"

# YouTube cookies arg
_YT_COOKIES_ARG = ["--cookies", YT_COOKIES_FILE] if os.path.exists(YT_COOKIES_FILE) else []


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
    
    cmd = [
        YT_DLP,
        "--no-playlist",
        "--no-warnings",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--add-metadata",
        "--embed-thumbnail",
        "-o", output_path,
        "--print", "after_move:filepath",
    ] + _YT_COOKIES_ARG + [
        f"https://music.youtube.com/watch?v={video_id}"
    ]
    
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "yt-dlp failed"
        return {"success": False, "error": err}
    
    path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if not path or not os.path.exists(path):
        return {"success": False, "error": "Файл не найден после скачивания"}
    
    return {"success": True, "path": path, "title": f"{safe_artist} - {safe_title}"}


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
