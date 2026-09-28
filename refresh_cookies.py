#!/usr/bin/env python3
"""Extract YouTube cookies from live Chromium via CDP and save as Netscape txt.

Usage:
    python refresh_cookies.py [--output PATH] [--browser-url URL]

Default output: $YT_COOKIES_FILE if set, else cookies/youtube.txt next to this script
(falling back to the container path /app/cookies/youtube.txt).
Default CDP endpoint: http://127.0.0.1:9222
"""

import json
import asyncio
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Default paths
def _default_cookies_path() -> str:
    """Prefer the checkout next to this script, else the container default."""
    sibling = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies", "youtube.txt")
    return sibling if os.path.isdir(os.path.dirname(sibling)) else "/app/cookies/youtube.txt"


DEFAULT_OUTPUT = os.getenv("YT_COOKIES_FILE") or _default_cookies_path()
DEFAULT_CDP_URL = "http://127.0.0.1:9222"

# Sites whose cookies we need for yt-dlp
COOKIE_URLS = [
    "https://www.youtube.com",
    "https://accounts.google.com",
    "https://music.youtube.com",
]


async def extract_cookies(cdp_url: str = DEFAULT_CDP_URL, output: str = DEFAULT_OUTPUT) -> int:
    """Connect to Chromium CDP, extract cookies, save as Netscape format."""
    # 1. Discover pages via CDP HTTP endpoint
    try:
        resp = urllib.request.urlopen(f"{cdp_url}/json", timeout=5)
        pages = json.loads(resp.read())
    except Exception as e:
        print(f"[ERROR] Chrome CDP недоступен на {cdp_url}: {e}", file=sys.stderr)
        print("[HINT] Проверь что Chromium запущен:", file=sys.stderr)
        print("  systemctl status vortex-chromium", file=sys.stderr)
        return 1

    # 2. Find any page (we just need a WebSocket to send Network.getCookies)
    ws_url = None
    for p in pages:
        if p.get("type") == "page" and p.get("webSocketDebuggerUrl"):
            ws_url = p["webSocketDebuggerUrl"]
            break

    if not ws_url:
        print("[ERROR] Не найдена страница в Chromium CDP", file=sys.stderr)
        return 1

    # 3. Get cookies via WebSocket
    try:
        import websockets
    except ImportError:
        print("[ERROR] websockets not installed. Run: pip install websockets", file=sys.stderr)
        return 1

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": COOKIE_URLS}
        }))
        result = json.loads(await ws.recv())
        cookies = result.get("result", {}).get("cookies", [])

    # 4. Filter: only keep cookies that are relevant for YouTube
    # yt-dlp needs: SID, HSID, SSID, APISID, SAPISID, __Secure-1PSID, __Secure-3PSID, etc.
    yt_cookies = []
    for c in cookies:
        if not c.get("name") or not c.get("value"):
            continue
        domain = c.get("domain", "")
        # Only YouTube/Google cookies
        if not any(d in domain for d in ["youtube.com", "google.com"]):
            continue
        if not domain.startswith("."):
            domain = "." + domain
        path = c.get("path", "/")
        secure = c.get("secure", False)
        expiry = int(c.get("expirationDate", 0) or 0)
        name = c["name"]
        value = c["value"]
        yt_cookies.append(
            f"{domain}\tTRUE\t{path}\t{'TRUE' if secure else 'FALSE'}\t{expiry}\t{name}\t{value}"
        )

    if not yt_cookies:
        print("[ERROR] Cookies не найдены. Залогинись в YouTube через Chromium сначала.", file=sys.stderr)
        print(f"[HINT] Открой http://<vps-ip>:6080/vnc.html или через SSH tunnel:", file=sys.stderr)
        print("  ssh -L 9222:127.0.0.1:9222 agent@<vps-ip>", file=sys.stderr)
        print("  Потом открой chrome://inspect → Configure → 127.0.0.1:9222", file=sys.stderr)
        return 1

    # 5. Save as Netscape format
    lines = ["# Netscape HTTP Cookie File"]
    lines.append(f"# Generated: {datetime.now().isoformat()}")
    lines.append(f"# Source: {len(yt_cookies)} cookies from Chromium CDP")
    lines.extend(yt_cookies)

    # Ensure output directory exists
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[{datetime.now().isoformat()}] YouTube cookies: {len(yt_cookies)} cookies saved to {output}")

    # 6. Also copy to the Docker volume backing /app/cookies, if this host has it.
    # Prefer the docker CLI (no root needed); fall back to the volume dir directly.
    docker_volume = "/var/lib/docker/volumes/vortex-cookies/_data/youtube.txt"
    if os.path.exists(os.path.dirname(docker_volume)):
        try:
            import shutil
            shutil.copy2(output, docker_volume)
            print(f"  → Copied to Docker volume: {docker_volume}")
        except (OSError, PermissionError) as e:
            print(f"  ⚠️ Не смог скопировать в Docker volume: {e}", file=sys.stderr)

    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract YouTube cookies from Chromium CDP")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT, help="Output file path")
    parser.add_argument("--browser-url", "-u", default=DEFAULT_CDP_URL, help="Chrome CDP URL")
    args = parser.parse_args()

    sys.exit(asyncio.run(extract_cookies(cdp_url=args.browser_url, output=args.output)))


if __name__ == "__main__":
    main()