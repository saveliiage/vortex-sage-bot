"""TikTok via Apify — used because VPS-IP is blocked by TikTok directly."""

import os
import re
import uuid
import httpx

from config import APIFY_TOKEN, DOWNLOAD_DIR

ACTOR = "clockworks~free-tiktok-scraper"
RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"


def fetch_metadata(url: str) -> dict:
    """Run Apify TikTok actor, return first result with downloadable mp4."""
    if not APIFY_TOKEN:
        return {"success": False, "error": "APIFY_TOKEN не задан в .env"}

    payload = {
        "postURLs": [url],
        "resultsPerPage": 1,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }
    try:
        r = httpx.post(
            RUN_URL,
            params={"token": APIFY_TOKEN},
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        return {"success": False, "error": f"Apify запрос упал: {e}"}
    except ValueError:
        return {"success": False, "error": "Apify вернул не-JSON"}

    if not data:
        return {"success": False, "error": "Apify вернул пустой результат"}

    item = data[0]
    media = item.get("mediaUrls") or []
    video_url = media[0] if media else item.get("videoUrl") or item.get("video", {}).get("downloadAddr")
    if not video_url:
        return {"success": False, "error": "В ответе Apify нет ссылки на mp4"}

    return {
        "success": True,
        "title": (item.get("text") or item.get("desc") or "TikTok video")[:100],
        "video_url": video_url,
        "thumbnail": item.get("videoMeta", {}).get("coverUrl") or item.get("covers", [None])[0] or "",
        "duration": item.get("videoMeta", {}).get("duration") or item.get("duration") or 0,
        "platform": "TikTok",
        "webpage_url": item.get("webVideoUrl") or url,
    }


def download_video(url: str) -> dict:
    meta = fetch_metadata(url)
    if not meta["success"]:
        return meta

    safe_title = re.sub(r"[^\w\-_. ]", "_", meta["title"])[:80] or "tiktok"
    fname = f"tt_{uuid.uuid4().hex[:8]}_{safe_title}.mp4"
    fpath = os.path.join(DOWNLOAD_DIR, fname)

    try:
        with httpx.stream("GET", meta["video_url"], timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(fpath, "wb") as f:
                for chunk in r.iter_bytes(64 * 1024):
                    f.write(chunk)
    except httpx.HTTPError as e:
        if os.path.exists(fpath):
            os.unlink(fpath)
        return {"success": False, "error": f"Не удалось скачать TikTok: {e}"}

    return {"success": True, "path": fpath, "title": meta["title"]}


def download_thumbnail(url: str) -> dict:
    meta = fetch_metadata(url)
    if not meta["success"]:
        return meta
    if not meta.get("thumbnail"):
        return {"success": False, "error": "Превью не найдено"}
    fname = f"tt_thumb_{uuid.uuid4().hex[:8]}.jpg"
    fpath = os.path.join(DOWNLOAD_DIR, fname)
    try:
        r = httpx.get(meta["thumbnail"], timeout=30, follow_redirects=True)
        r.raise_for_status()
        with open(fpath, "wb") as f:
            f.write(r.content)
    except httpx.HTTPError as e:
        return {"success": False, "error": f"Превью: {e}"}
    return {"success": True, "path": fpath}
