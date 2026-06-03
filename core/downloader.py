"""Media downloader — routes per-platform: Instagram (embed), TikTok (Apify), rest (yt-dlp)."""

import os
import re
import json
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

from config import DOWNLOAD_DIR, YT_COOKIES_FILE
from core import instagram, apify_tiktok

YT_DLP = "/opt/vortex/venv/bin/yt-dlp"
FFMPEG = "ffmpeg"

# YouTube cookies flag — only for yt-dlp calls, not for Instagram/TikTok
_YT_COOKIES_ARG = ["--cookies-from-browser", "chromium", "--remote-components", "ejs:github"]


def _platform(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.lower().lstrip("www.")
    if "instagram.com" in host:
        return "instagram"
    if "tiktok.com" in host:
        return "tiktok"
    return "ytdlp"


def _run_ytdlp(args: list, want_path: bool = False) -> dict:
    """Run yt-dlp. If want_path — args must include `--print after_move:filepath`."""
    full = [YT_DLP, "--no-playlist", "--no-warnings"] + _YT_COOKIES_ARG + args
    proc = subprocess.run(full, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "yt-dlp failed"
        return {"success": False, "error": err}
    out = proc.stdout.strip()
    if want_path:
        path = out.splitlines()[-1].strip() if out else ""
        if not path or not os.path.exists(path):
            return {"success": False, "error": "yt-dlp не вернул путь к файлу"}
        return {"success": True, "path": path, "output": out}
    return {"success": True, "output": out}


def _ffmpeg_to_mp3(src: str) -> dict:
    """Convert any media to mp3."""
    dst = os.path.splitext(src)[0] + f"_{uuid.uuid4().hex[:6]}.mp3"
    proc = subprocess.run(
        [FFMPEG, "-y", "-i", src, "-vn", "-acodec", "libmp3lame", "-q:a", "2", dst],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        return {"success": False, "error": f"ffmpeg: {proc.stderr.strip()[-200:]}"}
    return {"success": True, "path": dst}


# ---------- Public API (called by handlers) ----------

def get_info(url: str) -> dict:
    """Metadata only — title, duration, platform, etc."""
    plat = _platform(url)
    if plat == "instagram":
        meta = instagram.fetch_metadata(url)
        if not meta["success"]:
            return meta
        return {**meta, "ext": "mp4", "filesize": 0}
    if plat == "tiktok":
        meta = apify_tiktok.fetch_metadata(url)
        if not meta["success"]:
            return meta
        return {**meta, "ext": "mp4", "filesize": 0}

    res = _run_ytdlp(["--dump-json", url])
    if not res["success"]:
        return res
    try:
        info = json.loads(res["output"].splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        return {"success": False, "error": f"Не разобрал JSON: {e}"}
    return {
        "success": True,
        "title": info.get("title", "Untitled"),
        "duration": info.get("duration", 0),
        "ext": info.get("ext", "mp4"),
        "webpage_url": info.get("webpage_url", url),
        "thumbnail": info.get("thumbnail", ""),
        "filesize": info.get("filesize", 0) or info.get("filesize_approx", 0),
        "platform": info.get("extractor_key", "unknown"),
    }


def download_video(url: str) -> dict:
    plat = _platform(url)
    if plat == "instagram":
        return instagram.download_video(url)
    if plat == "tiktok":
        return apify_tiktok.download_video(url)

    output_template = os.path.join(DOWNLOAD_DIR, "%(title).100s_%(epoch)s.%(ext)s")
    # "best" fallback handles platforms where filesize metadata is missing (Pinterest HLS, etc.)
    return _run_ytdlp(
        [
            "-f", "best[filesize<50M]/bestvideo+bestaudio/best",
            "-o", output_template,
            "--print", "after_move:filepath",
            url,
        ],
        want_path=True,
    )


def download_audio(url: str) -> dict:
    """Return mp3. For Instagram/TikTok — download mp4 then convert."""
    plat = _platform(url)
    if plat in ("instagram", "tiktok"):
        mod = instagram if plat == "instagram" else apify_tiktok
        vid = mod.download_video(url)
        if not vid["success"]:
            return vid
        mp3 = _ffmpeg_to_mp3(vid["path"])
        try:
            os.unlink(vid["path"])
        except OSError:
            pass
        return mp3

    output_template = os.path.join(DOWNLOAD_DIR, "%(title).100s_%(epoch)s.%(ext)s")
    return _run_ytdlp(
        [
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            "--print", "after_move:filepath",
            url,
        ],
        want_path=True,
    )


def download_thumbnail(url: str) -> dict:
    plat = _platform(url)
    if plat == "instagram":
        return instagram.download_thumbnail(url)
    if plat == "tiktok":
        return apify_tiktok.download_thumbnail(url)

    # Use fixed output name to locate the thumbnail file reliably.
    # --write-thumbnail writes <name>.jpg, --print filename gives us the media filename
    # but the thumbnail uses the same stem. We'll print the media filename, derive thumb path from it.
    output_template = os.path.join(DOWNLOAD_DIR, "thumb_%(epoch)s")
    res = _run_ytdlp(
        [
            "--skip-download",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "-o", output_template,
            "--print", "filename",
            url,
        ],
    )
    if not res["success"]:
        return res
    # The printed filename is <thumb_EPOCH>.<ext> (the video extension), thumbnail is <thumb_EPOCH>.jpg
    media_name = res["output"].strip()
    stem = os.path.splitext(media_name)[0]
    thumb_path = stem + ".jpg"
    if os.path.exists(thumb_path):
        return {"success": True, "path": thumb_path}
    # Fallback: search DOWNLOAD_DIR for matching thumb
    import glob
    candidates = glob.glob(os.path.join(DOWNLOAD_DIR, f"thumb_*.jpg"))
    if candidates:
        newest = max(candidates, key=os.path.getmtime)
        return {"success": True, "path": newest}
    return {"success": False, "error": "thumbnail file not found"}


def clean_downloads(hours: int = 1):
    import time
    now = time.time()
    for f in Path(DOWNLOAD_DIR).iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > hours * 3600:
            f.unlink()
