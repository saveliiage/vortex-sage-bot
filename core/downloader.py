"""Media downloader — routes per-platform: Instagram (embed), TikTok (yt-dlp → Apify), rest (yt-dlp)."""

import os
import re
import json
import logging
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

from config import DOWNLOAD_DIR
from core import instagram, tiktok, apify_tiktok, ytdlp

log = logging.getLogger(__name__)

FFMPEG = "ffmpeg"


def _platform(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.lower().lstrip("www.")
    if "instagram.com" in host:
        return "instagram"
    if "tiktok.com" in host:
        return "tiktok"
    return "ytdlp"


def _run_ytdlp(args: list, want_path: bool = False) -> dict:
    """Run yt-dlp. If want_path — args must include `--print after_move:filepath`.

    Anonymous first, the cookie jar only as a retry (see core.ytdlp.run).
    """
    return ytdlp.run(args, want_path=want_path)


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


# ---------- TikTok: yt-dlp primary, Apify fallback ----------

def _apify_enabled() -> bool:
    """Owner kill switch — flip TIKTOK_APIFY_FALLBACK=0 in .env to skip Apify entirely."""
    return os.getenv("TIKTOK_APIFY_FALLBACK", "1").strip().lower() not in ("0", "false", "no")


def _tiktok_or_fallback(action: str, url: str) -> dict:
    """Run the yt-dlp action for TikTok; on failure retry through Apify (video only).

    Apify's free TikTok actor only serves video files, so audio/thumbnail just report
    the yt-dlp error instead of burning a paid actor run for nothing.
    """
    res = getattr(tiktok, action)(url)
    if res.get("success"):
        return res
    if not _apify_enabled():
        return res
    if action != "download_video":
        return res
    log.warning("TikTok yt-dlp path failed (%s), falling back to Apify", res.get("error"))
    fallback = apify_tiktok.download_video(url)
    if not fallback.get("success"):
        return {"success": False, "error": f"{res.get('error')} | Apify: {fallback.get('error')}"}
    return fallback


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
        meta = _tiktok_or_fallback("fetch_metadata", url)
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
        return _tiktok_or_fallback("download_video", url)

    output_template = os.path.join(DOWNLOAD_DIR, "%(title).100s_%(epoch)s.%(ext)s")
    # Prefer avc1/H.264 — Telegram can't play AV1. Fallback chain covers sites without avc1.
    return _run_ytdlp(
        [
            "-f", "bestvideo[vcodec^=avc1]+bestaudio/bestvideo+bestaudio/best",
            "-o", output_template,
            "--print", "after_move:filepath",
            "--merge-output-format", "mp4",
            url,
        ],
        want_path=True,
    )


def get_formats(url: str) -> list:
    """Get available video formats from yt-dlp. Returns list of dicts with height, ext, filesize, format_id."""
    plat = _platform(url)
    if plat in ("instagram", "tiktok"):
        return []  # No format selection for these platforms

    res = _run_ytdlp(["--list-formats", "--print", "%(formats)s", url])
    if not res["success"]:
        return []

    # Use --dump-json to get format info
    res = _run_ytdlp(["--dump-json", url])
    if not res["success"]:
        return []

    try:
        info = json.loads(res["output"].splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return []

    # Best audio size (for total size estimate)
    audio_size = 0
    for f in info.get("formats", []):
        ac = f.get("acodec", "")
        vc = f.get("vcodec", "")
        if ac and ac != "none" and (not vc or vc == "none"):
            s = f.get("filesize") or f.get("filesize_approx") or 0
            if s > audio_size:
                audio_size = s

    # Per height pick the most Telegram-friendly codec:
    # avc1 (H.264 — plays everywhere incl. Telegram) > vp9 > av01 (Telegram can't play AV1)
    by_height = {}
    for f in info.get("formats", []):
        height = f.get("height")
        if not height or height < 144:
            continue
        vcodec = f.get("vcodec", "")
        if not vcodec or vcodec == "none":
            continue
        if vcodec.startswith("avc1"):
            pri = 0
        elif vcodec.startswith("vp9") or vcodec.startswith("vp09"):
            pri = 1
        else:
            pri = 2
        fps = f.get("fps") or 0
        filesize = f.get("filesize") or f.get("filesize_approx") or 0
        format_id = f.get("format_id", "")
        cur = by_height.get(height)
        if cur is None or pri < cur["pri"] or (pri == cur["pri"] and filesize > cur["filesize"]):
            by_height[height] = {"pri": pri, "fps": fps, "filesize": filesize, "format_id": format_id}

    formats = []
    for height, f in sorted(by_height.items(), key=lambda x: x[0], reverse=True):
        label = f"{height}p"
        if f["fps"] and f["fps"] > 30:
            label += f" {int(f['fps'])}fps"
        total_size = (f["filesize"] + audio_size) if (f["filesize"] and audio_size) else (f["filesize"] or audio_size)
        formats.append({
            "height": height,
            "label": label,
            "ext": "mp4",
            "filesize": total_size,
            "format_id": f["format_id"],
            "has_audio": True,  # audio is merged in separately — final file always has sound
        })
    return formats


def download_video_quality(url: str, format_id: str = None, max_height: int = None) -> dict:
    """Download video with specific quality. If format_id given, use it. If max_height, pick best up to that height."""
    plat = _platform(url)
    if plat == "instagram":
        return instagram.download_video(url)
    if plat == "tiktok":
        return _tiktok_or_fallback("download_video", url)

    output_template = os.path.join(DOWNLOAD_DIR, "%(title).100s_%(epoch)s.%(ext)s")

    if format_id:
        format_spec = format_id
    elif max_height:
        # Prefer avc1 (H.264): Telegram's player can't handle AV1/VP9-only uploads reliably.
        # bestvideo[height<=X][vcodec^=avc1] + bestaudio, fallback to any codec, fallback to single progressive file.
        format_spec = (
            f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio/"
            f"bestvideo[height<={max_height}]+bestaudio/"
            f"best[height<={max_height}]/best"
        )
    else:
        format_spec = "bestvideo[vcodec^=avc1]+bestaudio/bestvideo+bestaudio/best"

    return _run_ytdlp(
        [
            "-f", format_spec,
            "-o", output_template,
            "--print", "after_move:filepath",
            "--merge-output-format", "mp4",
            url,
        ],
        want_path=True,
    )


def download_audio(url: str) -> dict:
    """Return mp3. TikTok — yt-dlp extracts audio directly, Apify fallback is video-only."""
    plat = _platform(url)
    if plat == "tiktok":
        res = _tiktok_or_fallback("download_audio", url)
        if res.get("success"):
            return res
        # Apify serves mp4 only — pull the video and transcode it locally.
        if not _apify_enabled():
            return res
        log.warning("TikTok audio via yt-dlp failed (%s), falling back to Apify + ffmpeg", res.get("error"))
        vid = apify_tiktok.download_video(url)
        if not vid["success"]:
            return {"success": False, "error": f"{res.get('error')} | Apify: {vid.get('error')}"}
        mp3 = _ffmpeg_to_mp3(vid["path"])
        try:
            os.unlink(vid["path"])
        except OSError:
            pass
        return mp3
    if plat == "instagram":
        vid = instagram.download_video(url)
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
        res = _tiktok_or_fallback("download_thumbnail", url)
        if res.get("success"):
            return res
        if not _apify_enabled():
            return res
        log.warning("TikTok thumbnail via yt-dlp failed (%s), falling back to Apify", res.get("error"))
        fallback = apify_tiktok.download_thumbnail(url)
        if not fallback.get("success"):
            return {"success": False, "error": f"{res.get('error')} | Apify: {fallback.get('error')}"}
        return fallback

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
