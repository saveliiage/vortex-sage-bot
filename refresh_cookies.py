#!/usr/bin/env python3
"""Extract YouTube cookies from live Chromium via CDP and save as Netscape txt."""
import json, asyncio, websockets, urllib.request, os, sys
from datetime import datetime

YT_COOKIES_TXT = "/opt/vortex/cookies/youtube.txt"

async def extract():
    try:
        resp = urllib.request.urlopen('http://localhost:9222/json', timeout=5)
        pages = json.loads(resp.read())
    except Exception as e:
        print(f"Chrome CDP недоступен: {e}", file=sys.stderr)
        sys.exit(1)

    # Найти YouTube страницу
    yt_ws = None
    for p in pages:
        url = p.get('url', '')
        if 'youtube.com' in url and 'accounts.google' not in url and 'sw.sw' not in url and 'blob:' not in url:
            yt_ws = p['webSocketDebuggerUrl']
            break

    if not yt_ws:
        print("YouTube страница не найдена в открытых вкладках", file=sys.stderr)
        sys.exit(1)

    # YouTube → Netscape
    async with websockets.connect(yt_ws) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": ["https://www.youtube.com", "https://accounts.google.com"]}
        }))
        result = json.loads(await ws.recv())
        cookies = result.get("result", {}).get("cookies", [])

    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        if not c.get("name") or not c.get("value"):
            continue
        domain = c.get("domain", ".youtube.com")
        if not domain.startswith("."):
            domain = "." + domain
        path = c.get("path", "/")
        secure = c.get("secure", False)
        expiry = int(c.get("expirationDate", 0))
        name = c["name"]
        value = c["value"]
        lines.append(f"{domain}\tTRUE\t{path}\t{'TRUE' if secure else 'FALSE'}\t{expiry}\t{name}\t{value}")

    with open(YT_COOKIES_TXT, "w") as f:
        f.write("\n".join(lines) + "\n")
    
    print(f"[{datetime.now().isoformat()}] YouTube cookies: {len(cookies)} cookies saved to {YT_COOKIES_TXT}")
    return 0

if __name__ == "__main__":
    asyncio.run(extract())
