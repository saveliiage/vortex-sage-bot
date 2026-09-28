"""TikTok via yt-dlp — primary path.

yt-dlp 2026.08+ solves the TikTok JS challenge natively, so the VPS IP that used to
be blocked now gets the page fine. Apify stays as a fallback (core/apify_tiktok.py).

Two traps, both verified live on the server:

* YouTube cookies must NOT be sent to TikTok. The cookies volume also holds TikTok
  session cookies (ttwid / tt_csrf_token / msToken) written by the Chromium refresh
  job; passing that jar to yt-dlp makes TikTok answer 403 to every request. Same
  command without cookies returns the format list.
* TikTok's only H.264 rendition is 540p (`h264_*` ids); 720p/1080p exist only as
  bytevc1/h265, which Telegram's player does not handle. The ladder below prefers
  H.264 and falls back to h265 only when a post has no H.264 rendition at all.
"""

import json
import os
import re
import subprocess
import uuid

import httpx

from config import DOWNLOAD_DIR, YT_DLP_BIN

# H.264 first (Telegram-playable), then any mp4, then whatever is left.
FORMAT_LADDER = "best[ext=mp4][vcodec^=h264]/best[ext=mp4][vcodec^=avc1]/best[ext=mp4]/best"
AUDIO_FORMAT = "bestaudio/best"

_TIMEOUT = 600


def _base_args() -> list:
    """yt-dlp args for TikTok — deliberately without the cookie jar (see module docstring)."""
    return [YT_DLP_BIN, "--no-playlist", "--no-warnings"]


def _output_template() -> str:
    return os.path.join(DOWNLOAD_DIR, "%(title).100s_%(epoch)s.%(ext)s")


def _run(args: list, timeout: int = _TIMEOUT) -> dict:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "yt-dlp: превышено время ожидания"}
    except OSError as e:
        return {"success": False, "error": f"yt-dlp: {e}"}
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "yt-dlp failed"
        return {"success": False, "error": err}
    return {"success": True, "output": proc.stdout.strip()}


def probe(url: str) -> dict:
    """Run yt-dlp --dump-json once and return the raw info dict."""
    res = _run(_base_args() + ["--dump-json", url], timeout=180)
    if not res["success"]:
        return res
    try:
        info = json.loads(res["output"].splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        return {"success": False, "error": f"Не разобрал JSON TikTok: {e}"}
    return {"success": True, "info": info}


def fetch_metadata(url: str) -> dict:
    """Metadata for the info screen — same shape as the Apify module returns."""
    res = probe(url)
    if not res["success"]:
        return res
    info = res["info"]
    return {
        "success": True,
        "title": (info.get("title") or info.get("description") or "TikTok video")[:100],
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail") or "",
        "video_url": "",  # resolved only at download time, yt-dlp picks the rendition
        "platform": "TikTok",
        "webpage_url": info.get("webpage_url") or url,
    }


def download_video(url: str) -> dict:
    """Download with the H.264-first ladder. Returns {success, path, title}."""
    res = _run(
        _base_args()
        + [
            "-f", FORMAT_LADDER,
            "-o", _output_template(),
            "--print", "after_move:filepath",
            url,
        ]
    )
    if not res["success"]:
        return res
    path = res["output"].splitlines()[-1].strip() if res["output"] else ""
    if not path or not os.path.exists(path):
        return {"success": False, "error": "yt-dlp не вернул путь к файлу"}
    return {"success": True, "path": path, "title": _title_from_path(path)}


def download_audio(url: str) -> dict:
    """Extract audio as mp3 straight from the source (no video download + transcode)."""
    res = _run(
        _base_args()
        + [
            "-f", AUDIO_FORMAT,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", _output_template(),
            "--print", "after_move:filepath",
            url,
        ]
    )
    if not res["success"]:
        return res
    path = res["output"].splitlines()[-1].strip() if res["output"] else ""
    if not path or not os.path.exists(path):
        return {"success": False, "error": "yt-dlp не вернул путь к файлу"}
    return {"success": True, "path": path}


def download_thumbnail(url: str) -> dict:
    """yt-dlp --write-thumbnail does not fire for TikTok, so pull the cover from the dump."""
    res = probe(url)
    if not res["success"]:
        return res
    thumb_url = res["info"].get("thumbnail")
    if not thumb_url:
        return {"success": False, "error": "Превью не найдено"}

    fpath = os.path.join(DOWNLOAD_DIR, f"tt_thumb_{uuid.uuid4().hex[:8]}.jpg")
    try:
        r = httpx.get(thumb_url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        with open(fpath, "wb") as f:
            f.write(r.content)
    except httpx.HTTPError as e:
        return {"success": False, "error": f"Превью: {e}"}
    return {"success": True, "path": fpath}


def _title_from_path(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"_\d{9,}$", "", name)
