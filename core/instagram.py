"""Instagram fetcher.

Strategy:
1. Try the public embed page (free, instant, works for ~most public reels).
2. If embed doesn't return a video_url (some reels Instagram refuses to serve to
   datacenter IPs anonymously), fall back to Apify's apify/instagram-scraper.
"""

import json
import re
import os
import uuid
import logging
from urllib.parse import urlparse
import httpx

from config import DOWNLOAD_DIR, APIFY_TOKEN

log = logging.getLogger(__name__)

EMBED_TPL = "https://www.instagram.com/{kind}/{shortcode}/embed/captioned/"
# Try in order — facebookexternalhit is the most reliable (IG always serves public OG-data to FB's preview bot)
UAS = [
    "facebookexternalhit/1.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
]
MOBILE_UA = UAS[1]  # for direct media downloads
VIDEO_RE = re.compile(r'\\"video_url\\":\\"([^"]+?)\\"')
THUMB_RE = re.compile(r'\\"display_url\\":\\"([^"]+?)\\"')
CAPTION_RE = re.compile(r'\\"caption\\":\\"((?:[^"\\]|\\.)*?)\\"')


def _unescape(raw: str) -> str:
    """Unescape doubly-escaped JSON string from Instagram embed HTML."""
    s = raw
    for _ in range(2):
        try:
            s = json.loads(f'"{s}"')
        except (json.JSONDecodeError, ValueError):
            break
    return s


def _parse_shortcode(url: str) -> tuple[str, str] | None:
    """Extract (kind, shortcode) from an Instagram URL. kind ∈ {p, reel, tv}."""
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("p", "reel", "tv", "reels"):
        kind = "reel" if parts[0] in ("reel", "reels") else parts[0]
        return kind, parts[1]
    return None


def fetch_metadata(url: str) -> dict:
    """Get video URL + thumb + caption from Instagram embed page."""
    parsed = _parse_shortcode(url)
    if not parsed:
        return {"success": False, "error": "Не похоже на Instagram URL"}
    kind, shortcode = parsed

    embed_url = EMBED_TPL.format(kind=kind, shortcode=shortcode)
    body = ""
    last_err = ""
    for ua in UAS:
        try:
            r = httpx.get(embed_url, headers={"User-Agent": ua}, timeout=30, follow_redirects=True)
            r.raise_for_status()
            body = r.text
            if VIDEO_RE.search(body):
                break
            last_err = f"UA={ua[:40]} len={len(body)} — нет video_url"
        except httpx.HTTPError as e:
            last_err = f"UA={ua[:40]} — {e}"

    m = VIDEO_RE.search(body)
    if not m:
        log.info("IG embed didn't yield video_url, trying Apify fallback (%s)", last_err)
        apify = _apify_fallback(url)
        if apify["success"]:
            apify["shortcode"] = shortcode
            apify["webpage_url"] = f"https://www.instagram.com/{kind}/{shortcode}/"
            return apify
        return {
            "success": False,
            "error": f"Embed: {last_err}. Apify: {apify.get('error')}",
        }

    try:
        video_url = _unescape(m.group(1))
    except (json.JSONDecodeError, ValueError) as e:
        return {"success": False, "error": f"Не разобрал video_url: {e}"}

    thumb_match = THUMB_RE.search(body)
    caption_match = CAPTION_RE.search(body)
    thumbnail = ""
    if thumb_match:
        try:
            thumbnail = _unescape(thumb_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    title = shortcode
    if caption_match:
        try:
            decoded = _unescape(caption_match.group(1))
            title = decoded.split("\n")[0][:100] or shortcode
        except (json.JSONDecodeError, ValueError):
            pass

    return {
        "success": True,
        "title": title,
        "video_url": video_url,
        "thumbnail": thumbnail,
        "platform": "Instagram",
        "shortcode": shortcode,
        "webpage_url": f"https://www.instagram.com/{kind}/{shortcode}/",
    }


def _apify_fallback(url: str) -> dict:
    """Run apify/instagram-scraper for a single post. Returns same shape as fetch_metadata."""
    if not APIFY_TOKEN:
        return {"success": False, "error": "APIFY_TOKEN не задан"}

    endpoint = "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items"
    payload = {
        "directUrls": [url],
        "resultsType": "posts",
        "resultsLimit": 1,
        "addParentData": False,
    }
    try:
        r = httpx.post(endpoint, params={"token": APIFY_TOKEN}, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        return {"success": False, "error": f"Apify запрос упал: {e}"}
    except ValueError:
        return {"success": False, "error": "Apify вернул не-JSON"}

    if not data:
        return {"success": False, "error": "Apify пустой результат (приватный или удалён?)"}
    item = data[0]
    video_url = item.get("videoUrl") or (item.get("videoVersions") or [{}])[0].get("url")
    if not video_url:
        return {"success": False, "error": f"Apify: нет videoUrl (type={item.get('type')})"}

    title = (item.get("caption") or item.get("alt") or "").split("\n")[0][:100] or item.get("shortCode") or "Instagram post"
    return {
        "success": True,
        "title": title,
        "video_url": video_url,
        "thumbnail": item.get("displayUrl") or "",
        "platform": "Instagram",
        "duration": item.get("videoDuration") or 0,
    }


def download_video(url: str) -> dict:
    """Fetch IG embed → stream mp4 to disk. Returns local path."""
    meta = fetch_metadata(url)
    if not meta["success"]:
        return meta

    safe_title = re.sub(r"[^\w\-_. ]", "_", meta["title"])[:80] or meta["shortcode"]
    fname = f"ig_{meta['shortcode']}_{uuid.uuid4().hex[:6]}_{safe_title}.mp4"
    fpath = os.path.join(DOWNLOAD_DIR, fname)

    try:
        with httpx.stream("GET", meta["video_url"], headers={"User-Agent": MOBILE_UA}, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(fpath, "wb") as f:
                for chunk in r.iter_bytes(64 * 1024):
                    f.write(chunk)
    except httpx.HTTPError as e:
        if os.path.exists(fpath):
            os.unlink(fpath)
        return {"success": False, "error": f"Не удалось скачать видео: {e}"}

    return {"success": True, "path": fpath, "title": meta["title"]}


def download_thumbnail(url: str) -> dict:
    """Fetch IG embed → save thumbnail."""
    meta = fetch_metadata(url)
    if not meta["success"]:
        return meta
    if not meta.get("thumbnail"):
        return {"success": False, "error": "Превью не найдено"}

    fname = f"ig_thumb_{meta['shortcode']}_{uuid.uuid4().hex[:6]}.jpg"
    fpath = os.path.join(DOWNLOAD_DIR, fname)
    try:
        r = httpx.get(meta["thumbnail"], headers={"User-Agent": MOBILE_UA}, timeout=30, follow_redirects=True)
        r.raise_for_status()
        with open(fpath, "wb") as f:
            f.write(r.content)
    except httpx.HTTPError as e:
        return {"success": False, "error": f"Превью: {e}"}
    return {"success": True, "path": fpath}
