"""Instagram fetcher.

Strategy:
1. Parse the public embed page. Its `contextJSON` payload carries the whole post —
   single photo, carousel (all children, full resolution) or reel — so one parse covers
   every post type.
2. Fall back to the older plain regexes on the same page (reels only).
3. Fall back to Apify's apify/instagram-scraper (video posts only).
"""

import json
import re
import os
import time
import uuid
import logging
from urllib.parse import urlparse
import httpx

from config import DOWNLOAD_DIR, APIFY_TOKEN, IG_COOKIES_FILE

log = logging.getLogger(__name__)

EMBED_TPL = "https://www.instagram.com/{kind}/{shortcode}/embed/captioned/"
# Try in order — facebookexternalhit is the most reliable (IG always serves public OG-data to FB's preview bot)
UAS = [
    "facebookexternalhit/1.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
]
MOBILE_UA = UAS[1]  # for direct media downloads
VIDEO_RE = re.compile(r'\\\\"video_url\\\\":\\\\"([^"]+?)\\\\"')
THUMB_RE = re.compile(r'\\\\"display_url\\\\":\\\\"([^"]+?)\\\\"')
CAPTION_RE = re.compile(r'\\\\"caption\\\\":\\\\"((?:[^"\\\\]|\\\\.)*?)\\\\"')
CTX_MARKER = '"contextJSON":"'
FULL_SIZE_WIDTH = 1000  # display_resources below this are downscaled copies
MAX_ALBUM_ITEMS = 10  # Telegram media group limit

# ── Stories ───────────────────────────────────────────────────────────────────────────────
# A story link cannot be fetched anonymously: Instagram answers a logged-out visitor with a
# signup wall and no media at all. The web API below therefore needs the user's own cookie
# jar, and the code says so out loud instead of failing with a generic error.
IG_APP_ID = "936619743392459"  # the id the Instagram web app itself sends
STORY_RE = re.compile(
    r"instagram\.com/stories/(?:(highlights)/(\d+)|([A-Za-z0-9._]+)(?:/(\d+))?)", re.I
)
STORY_NEEDS_LOGIN = "STORIES_NEED_LOGIN"


def _unescape(raw: str) -> str:
    """Unescape doubly-escaped JSON string from Instagram embed HTML."""
    s = raw
    for _ in range(2):
        try:
            s = json.loads(f'"{s}"')
        except (json.JSONDecodeError, ValueError):
            break
    return s


IG_HOSTS = ("instagram.com", "instagr.am", "ig.me")
_POST_KINDS = ("p", "reel", "reels", "tv")
# path words that sit right after a kind marker but are pages, not posts
_NOT_CODES = {"audio", "share", "explore", "stories", "highlights", "accounts", "direct"}


def _parse_shortcode(url: str) -> tuple[str, str] | None:
    """Extract (kind, shortcode) from an Instagram URL. kind ∈ {p, reel, tv}.

    Instagram hands out several shapes of the same link — `/p/<code>/`, `/reel/<code>/`,
    `/reels/<code>/`, `/<handle>/reel/<code>/` and the share form `/share/reel/<token>/` —
    so the kind marker is looked for anywhere in the path instead of only at its start.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").lower().split("@")[-1].split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in IG_HOSTS):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part in _POST_KINDS and index + 1 < len(parts):
            code = parts[index + 1].strip()
            if not code or code in _POST_KINDS or code.lower() in _NOT_CODES:
                continue
            return ("reel" if part == "reels" else part), code
    return None


def _looks_shared(url: str) -> bool:
    """True for the app share links, /share/reel/<token>/ and /share/p/<token>/."""
    return "share" in [part for part in urlparse(url).path.split("/") if part]


def _resolve_share(url: str) -> str:
    """Follow a /share/... link to the canonical post URL. Empty string when it fails."""
    try:
        r = httpx.get(url, headers={"User-Agent": MOBILE_UA}, timeout=30, follow_redirects=True)
    except httpx.HTTPError as e:
        log.warning("IG share link did not resolve: %s", e)
        return ""
    final = str(r.url)
    if not _looks_shared(final):
        return final
    match = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', r.text) or re.search(
        r'<meta[^>]+property="og:url"[^>]+content="([^"]+)"', r.text
    )
    return match.group(1) if match else ""


def _slice_json_string(body: str, start: int) -> str | None:
    """Raw content of a JSON string that begins at `start`.

    Instagram escapes this payload twice (it is JSON inside a JSON string), so the closing
    quote is the first one preceded by an even number of backslashes.
    """
    out = []
    backslashes = 0
    for ch in body[start:]:
        if ch == "\\":
            backslashes += 1
            out.append(ch)
            continue
        if ch == '"' and backslashes % 2 == 0:
            return "".join(out)
        backslashes = 0
        out.append(ch)
        if len(out) > 2_000_000:
            return None
    return None


def _decode_layers(text: str, depth: int = 4) -> dict | None:
    """json.loads the text, peeling one escaping layer at a time until it yields a dict."""
    current = text
    for _ in range(depth):
        try:
            value = json.loads(current)
        except (json.JSONDecodeError, ValueError):
            value = None
        if isinstance(value, dict):
            return value
        try:
            current = json.loads('"' + current + '"')
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _post_media(body: str) -> dict | None:
    """shortcode_media object out of the embed's contextJSON, None when not published."""
    index = body.find(CTX_MARKER)
    if index < 0:
        return None
    raw = _slice_json_string(body, index + len(CTX_MARKER))
    if not raw:
        return None
    data = _decode_layers(raw) or {}
    return ((data.get("gql_data") or {}).get("shortcode_media") or None)


def _best_image(node: dict) -> str:
    """Full-resolution image URL of one media node."""
    best = node.get("display_url") or ""
    for res in node.get("display_resources") or []:
        if (res.get("config_width") or 0) >= FULL_SIZE_WIDTH and res.get("src"):
            best = res["src"]
    return best


def _post_items(media: dict) -> list:
    """Flatten a post into [{'type': 'photo'|'video', 'url': ...}]."""
    children = ((media.get("edge_sidecar_to_children") or {}).get("edges") or [])
    nodes = [edge.get("node") or {} for edge in children] or [media]
    items = []
    for node in nodes:
        if node.get("is_video"):
            url = node.get("video_url") or ""
            if url:
                items.append({"type": "video", "url": url})
            continue
        url = _best_image(node)
        if url:
            items.append({"type": "photo", "url": url})
    return items


def _post_caption(media: dict) -> str:
    for edge in ((media.get("edge_media_to_caption") or {}).get("edges") or []):
        text = ((edge.get("node") or {}).get("text") or "").strip()
        if text:
            return text
    return ""


def _embed_body(url: str) -> tuple[str, str, str, str]:
    """(body, shortcode, kind, last_error) for an Instagram URL.

    Instagram intermittently answers with an app shell that carries no post data at all
    (a ~490 KB page instead of the ~200 KB embed), so the request is retried a couple of
    times before giving up — one bad page says nothing about the post itself.
    """
    if _looks_shared(url):
        resolved = _resolve_share(url)
        if resolved:
            log.info("IG share link resolved to %s", resolved[:160])
            url = resolved
        else:
            log.info("IG share link not resolved, trying it as is: %s", url[:160])

    parsed = _parse_shortcode(url)
    if not parsed:
        log.info("IG link not recognized: %s", url[:160])
        return "", "", "", "Не похоже на ссылку Instagram"
    kind, shortcode = parsed

    embed_url = EMBED_TPL.format(kind=kind, shortcode=shortcode)
    body = ""
    last_err = ""
    for attempt in range(2):
        for ua in UAS:
            try:
                r = httpx.get(embed_url, headers={"User-Agent": ua}, timeout=30, follow_redirects=True)
                r.raise_for_status()
                body = r.text
                if CTX_MARKER in body or VIDEO_RE.search(body):
                    return body, shortcode, kind, ""
                last_err = f"UA={ua[:40]} len={len(body)} — нет данных поста"
            except httpx.HTTPError as e:
                last_err = f"UA={ua[:40]} — {e}"
        if attempt < 1:
            time.sleep(2)
    return body, shortcode, kind, last_err


def parse_post(url: str) -> dict:
    """Everything a post holds — kind ∈ {video, photo, album}, items with media URLs."""
    body, shortcode, kind, last_err = _embed_body(url)
    if not body:
        return {"success": False, "error": last_err or "Instagram не отдал страницу поста"}

    media = _post_media(body)
    if media:
        items = _post_items(media)
        if items:
            caption = _post_caption(media)
            title = caption.split("\n")[0][:100] or shortcode
            if len(items) > 1:
                post_kind = "album"
            else:
                post_kind = items[0]["type"]
            return {
                "success": True,
                "kind": post_kind,
                "items": items,
                "title": title,
                "caption": caption,
                "thumbnail": _best_image(media) or next(
                    (i["url"] for i in items if i["type"] == "photo"), ""
                ),
                "platform": "Instagram",
                "shortcode": shortcode,
                "webpage_url": f"https://www.instagram.com/{kind}/{shortcode}/",
            }

    # Older reels pages only carry the plain video_url / display_url fields.
    match = VIDEO_RE.search(body)
    if match:
        try:
            video_url = _unescape(match.group(1))
        except (json.JSONDecodeError, ValueError) as e:
            return {"success": False, "error": f"Не разобрал video_url: {e}"}
        thumbnail = ""
        thumb_match = THUMB_RE.search(body)
        if thumb_match:
            try:
                thumbnail = _unescape(thumb_match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass
        title = shortcode
        caption_match = CAPTION_RE.search(body)
        if caption_match:
            try:
                title = _unescape(caption_match.group(1)).split("\n")[0][:100] or shortcode
            except (json.JSONDecodeError, ValueError):
                pass
        return {
            "success": True,
            "kind": "video",
            "items": [{"type": "video", "url": video_url}],
            "title": title,
            "caption": "",
            "thumbnail": thumbnail,
            "platform": "Instagram",
            "shortcode": shortcode,
            "webpage_url": f"https://www.instagram.com/{kind}/{shortcode}/",
        }

    log.info("IG embed didn't yield post data, trying Apify fallback (%s)", last_err)
    apify = _apify_fallback(url)
    if apify.get("success"):
        apify["shortcode"] = shortcode
        apify["webpage_url"] = f"https://www.instagram.com/{kind}/{shortcode}/"
        return apify
    return {"success": False, "error": f"Embed: {last_err}. Apify: {apify.get('error')}"}


def fetch_metadata(url: str) -> dict:
    """Metadata for one post. Keeps the historical shape (`video_url` for video posts)."""
    post = parse_post(url)
    if not post.get("success"):
        return post
    meta = dict(post)
    first_video = next((i["url"] for i in post["items"] if i["type"] == "video"), "")
    if first_video:
        meta["video_url"] = first_video
    return meta


def _apify_node(node: dict) -> dict | None:
    """One media entry out of an Apify post or child record."""
    if node.get("videoUrl"):
        return {"type": "video", "url": node["videoUrl"]}
    if node.get("displayUrl"):
        return {"type": "photo", "url": node["displayUrl"]}
    return None


def _apify_items(item: dict) -> list:
    """Every media of a post — children first, then the record itself, then the images list."""
    items = []
    for child in item.get("childPosts") or []:
        entry = _apify_node(child)
        if entry:
            items.append(entry)
    if not items:
        entry = _apify_node(item)
        if entry:
            items.append(entry)
    if not items:
        for url in item.get("images") or []:
            if url:
                items.append({"type": "photo", "url": url})
    return items


def _apify_fallback(url: str) -> dict:
    """Run apify/instagram-scraper for a single post. Photos and carousels included."""
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
    items = _apify_items(item)
    if not items:
        return {"success": False, "error": f"Apify без медиа (type={item.get('type')})"}

    caption = (item.get("caption") or item.get("alt") or "").strip()
    title = caption.split("\n")[0][:100] or item.get("shortCode") or "Instagram post"
    videos = [entry["url"] for entry in items if entry["type"] == "video"]
    result = {
        "success": True,
        "kind": "album" if len(items) > 1 else items[0]["type"],
        "items": items,
        "title": title,
        "caption": caption,
        "thumbnail": items[0]["url"],
        "platform": "Instagram",
        "duration": item.get("videoDuration") or 0,
    }
    if videos:
        result["video_url"] = videos[0]
    return result


def story_target(url: str) -> tuple[str, str, str] | None:
    """(handle, story_id, highlight_id) for a story URL, None when it is not one."""
    if "instagram.com" not in (url or "").lower():
        return None
    match = STORY_RE.search(url)
    if not match:
        return None
    highlight_id = match.group(2) or ""
    handle = match.group(3) or ""
    story_id = match.group(4) or ""
    if not handle and not highlight_id:
        return None
    return handle, story_id, highlight_id


def _ig_jar() -> dict:
    """Netscape cookie file -> plain cookie dict. Values are never logged."""
    path = IG_COOKIES_FILE if (IG_COOKIES_FILE and os.path.exists(IG_COOKIES_FILE)) else ""
    if not path:
        return {}
    jar = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                if raw.startswith("#HttpOnly_"):
                    raw = raw[len("#HttpOnly_"):]
                elif raw.startswith("#"):
                    continue
                parts = raw.split("\t")
                if len(parts) < 7 or "instagram" not in parts[0]:
                    continue
                jar[parts[5]] = parts[6]
    except OSError as e:
        log.warning("IG cookie jar unreadable: %s", e)
    return jar


def _story_client(jar: dict) -> httpx.Client:
    """Client that looks like the Instagram web app, carrying the user's session."""
    return httpx.Client(
        headers={
            "User-Agent": MOBILE_UA,
            "x-ig-app-id": IG_APP_ID,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.instagram.com/",
        },
        cookies=jar,
        timeout=40,
        follow_redirects=True,
    )


def _story_buckets(data: dict) -> list:
    """Media items out of a reels_media answer, both response shapes Instagram uses."""
    buckets = []
    reels = data.get("reels") or {}
    if isinstance(reels, dict):
        buckets.extend(value for value in reels.values() if isinstance(value, dict))
    reels_media = data.get("reels_media") or []
    if isinstance(reels_media, list):
        buckets.extend(value for value in reels_media if isinstance(value, dict))
    items = []
    for bucket in buckets:
        items.extend(bucket.get("items") or [])
    return items


def _story_entry(item: dict) -> dict | None:
    """One story item -> {type, url, id, thumb} with the biggest media available."""
    best_image = ""
    candidates = ((item.get("image_versions2") or {}).get("candidates") or [])
    if candidates:
        best_image = max(candidates, key=lambda c: (c.get("width") or 0) * (c.get("height") or 0)).get("url") or ""

    versions = item.get("video_versions") or []
    if versions:
        best = max(versions, key=lambda v: (v.get("width") or 0) * (v.get("height") or 0))
        if best.get("url"):
            return {"type": "video", "url": best["url"], "id": str(item.get("pk") or ""), "thumb": best_image}
    if best_image:
        return {"type": "photo", "url": best_image, "id": str(item.get("pk") or ""), "thumb": ""}
    return None


def _story_user_pk(client: httpx.Client, handle: str) -> str:
    """Numeric profile id for a handle, needed by reels_media."""
    try:
        r = client.get("https://www.instagram.com/api/v1/users/web_profile_info/",
                       params={"username": handle})
        r.raise_for_status()
        user = ((r.json().get("data") or {}).get("user") or {})
        return str(user.get("id") or "")
    except (httpx.HTTPError, ValueError) as e:
        log.warning("IG profile lookup failed for %s: %s", handle, e)
        return ""


def _story_media(handle: str, story_id: str, highlight_id: str) -> dict:
    """Active stories of a handle, or every item of a highlight. Needs the cookie jar."""
    jar = _ig_jar()
    if not jar.get("sessionid"):
        return {"success": False, "error": STORY_NEEDS_LOGIN}

    with _story_client(jar) as client:
        key = highlight_id or _story_user_pk(client, handle)
        if not key:
            return {"success": False, "error": "Instagram не отдал профиль, cookies протухли"}
        try:
            r = client.get("https://www.instagram.com/api/v1/feed/reels_media/",
                           params={"reels_media": f"[{key}]"})
            r.raise_for_status()
            items = _story_buckets(r.json())
        except (httpx.HTTPError, ValueError) as e:
            return {"success": False, "error": f"Instagram не отдал сторис: {e}"}

    entries = [entry for entry in (_story_entry(item) for item in items) if entry]
    if not entries:
        return {"success": False, "error": "Активных сторис нет"}

    if story_id:
        picked = [entry for entry in entries if entry["id"] == story_id]
        if not picked:
            return {"success": False, "error": "Этой сторис уже нет, она пропала или закрыта"}
        entries = picked

    return {
        "success": True,
        "kind": "album" if len(entries) > 1 else entries[0]["type"],
        "items": entries,
        "title": f"Сторис {handle or 'Instagram'}",
        "handle": handle,
    }


def _save_media(url: str, path: str, timeout: int = 120) -> bool:
    """Stream one media URL to disk. Removes the partial file when the transfer fails."""
    try:
        with httpx.stream("GET", url, headers={"User-Agent": MOBILE_UA}, timeout=timeout,
                          follow_redirects=True) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes(64 * 1024):
                    f.write(chunk)
        return os.path.getsize(path) > 0
    except (httpx.HTTPError, OSError) as e:
        log.warning("IG media download failed (%s): %s", url[:80], e)
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        return False


def _save_thumbnail(url: str, shortcode: str) -> str:
    """Cover file for sendVideo — Telegram does not generate one for large videos."""
    if not url:
        return ""
    candidate = os.path.join(DOWNLOAD_DIR, f"ig_thumb_{shortcode}_{uuid.uuid4().hex[:6]}.jpg")
    return candidate if _save_media(url, candidate, timeout=30) else ""


def _safe_slug(title: str, shortcode: str) -> str:
    return re.sub(r"[^\w\-_. ]", "_", title)[:80] or shortcode


def download_post(url: str) -> dict:
    """Download every media item of a post — photo, carousel or reel.

    Returns {success, kind, items: [{type, path}], title, thumbnail_path}.
    """
    post = parse_post(url)
    if not post.get("success"):
        return post

    shortcode = post["shortcode"]
    slug = _safe_slug(post["title"], shortcode)
    items = []
    for index, entry in enumerate(post["items"][:MAX_ALBUM_ITEMS], 1):
        ext = "mp4" if entry["type"] == "video" else "jpg"
        path = os.path.join(DOWNLOAD_DIR, f"ig_{shortcode}_{uuid.uuid4().hex[:6]}_{index}_{slug}.{ext}")
        if _save_media(entry["url"], path):
            items.append({"type": entry["type"], "path": path})

    if not items:
        return {"success": False, "error": "Не удалось скачать фото" if post["kind"] != "video"
                else "Не удалось скачать видео"}

    result = {
        "success": True,
        "kind": post["kind"],
        "items": items,
        "title": post["title"],
        "caption": post.get("caption", ""),
        "total_items": len(post["items"]),
    }
    if post["kind"] == "video":
        result["path"] = items[0]["path"]
        result["thumbnail_path"] = _save_thumbnail(post.get("thumbnail", ""), shortcode)
    return result


def parse_story(url: str) -> dict:
    """Metadata for a story link — one item or a whole highlight, photo or video."""
    target = story_target(url)
    if not target:
        return {"success": False, "error": "Не похоже на ссылку сторис Instagram"}
    handle, story_id, highlight_id = target
    post = _story_media(handle, story_id, highlight_id)
    if not post.get("success"):
        return post
    post["shortcode"] = story_id or highlight_id
    post["webpage_url"] = f"https://www.instagram.com/stories/{handle}/"
    return post


def download_story(url: str) -> dict:
    """Download the media behind a story link. {success, kind, items: [{type, path}], title}."""
    post = parse_story(url)
    if not post.get("success"):
        return post

    stem = re.sub(r"[^\w.\-]", "_", post.get("handle") or "story")[:40] or "story"
    items = []
    for index, entry in enumerate(post["items"][:MAX_ALBUM_ITEMS], 1):
        ext = "mp4" if entry["type"] == "video" else "jpg"
        path = os.path.join(DOWNLOAD_DIR, f"igstory_{stem}_{uuid.uuid4().hex[:6]}_{index}.{ext}")
        if _save_media(entry["url"], path):
            items.append({"type": entry["type"], "path": path})

    if not items:
        return {"success": False, "error": "Не удалось скачать сторис"}

    result = {
        "success": True,
        "kind": post["kind"],
        "items": items,
        "title": post["title"],
        "total_items": len(post["items"]),
    }
    if post["kind"] == "video":
        result["path"] = items[0]["path"]
        result["thumbnail_path"] = _save_thumbnail(post["items"][0].get("thumb", ""), stem)
    return result


def download_video(url: str) -> dict:
    """Video-only entry point kept for the audio/quality paths. {path, title, thumbnail_path}."""
    post = download_post(url)
    if not post.get("success"):
        return post

    video = next((item for item in post["items"] if item["type"] == "video"), None)
    for item in post["items"]:
        if item is not video:
            try:
                os.unlink(item["path"])
            except OSError:
                pass
    if not video:
        return {"success": False, "error": "В этом посте нет видео, только фото"}

    return {
        "success": True,
        "path": video["path"],
        "title": post["title"],
        "thumbnail_path": post.get("thumbnail_path", ""),
    }


def download_thumbnail(url: str) -> dict:
    """Fetch IG embed → save the post image."""
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
