#!/usr/bin/env python3
"""
Vortex MCP Server — stdio transport.
Shares core modules with the Telegram bot: subtitles_json3.py, summarizer.py

Tools:
  - summarize_youtube(url, lang, with_transcript)
  - fetch_transcript(url, lang)
  - quick_summary(url, lang)

Add to ~/.hermes/config.yaml:
  mcp_servers:
    vortex:
      command: "python3"
      args: ["PATH/TO/vortex_mcp_server.py"]
      env:
        GOOGLE_AI_API_KEY: "..."
      timeout: 180
"""

import json
import os
import sys
from pathlib import Path

# ── Ensure bot core is importable ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from core.summarizer import summarize_video
from core.subtitles_json3 import fetch_transcript

# ── Optional API key from env ─────────────────────────────────────────────────
GOOGLE_AI_KEY = os.environ.get("GOOGLE_AI_API_KEY")
if not GOOGLE_AI_KEY:
    # Try bot .env
    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GOOGLE_AI_API_KEY="):
                GOOGLE_AI_KEY = line.split("=", 1)[1].strip().strip('"')
                os.environ["GOOGLE_AI_API_KEY"] = GOOGLE_AI_KEY
                break

SERVER_NAME = "vortex"
SERVER_VERSION = "2.0.0"

TOOLS = {
    "summarize_youtube": {
        "description": "Full YouTube summary with optional transcript. Returns structured markdown summary with sections, timestamps and quotes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube URL or video ID"},
                "lang": {"type": "string", "default": "ru-orig,ru,en", "description": "Subtitle languages (comma-separated)"},
                "with_transcript": {"type": "boolean", "default": False, "description": "Include full transcript in output"},
            },
            "required": ["url"],
        },
    },
    "fetch_transcript": {
        "description": "Download and clean YouTube subtitles. Returns cleaned transcript with timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "lang": {"type": "string", "default": "ru-orig,ru,en"},
            },
            "required": ["url"],
        },
    },
    "quick_summary": {
        "description": "Fast 3-5 sentence summary of a YouTube video. No timestamps, no quotes — just the gist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "lang": {"type": "string", "default": "ru-orig,ru,en"},
            },
            "required": ["url"],
        },
    },
}


def handle_request(req: dict) -> dict:
    method = req.get("method")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [{"name": k, **v} for k, v in TOOLS.items()]},
        }

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            if name == "summarize_youtube":
                result = summarize_video(
                    args["url"],
                    with_transcript=args.get("with_transcript", False),
                    lang=args.get("lang", "ru-orig,ru,en"),
                )
            elif name == "fetch_transcript":
                result = fetch_transcript(args["url"], languages=args.get("lang", "ru-orig,ru,en"))
            elif name == "quick_summary":
                # Quick: just summary without full formatting, truncate to keep it fast
                full = summarize_video(
                    args["url"],
                    with_transcript=False,
                    lang=args.get("lang", "ru-orig,ru,en"),
                )
                if full.get("success") and full.get("summary"):
                    text = full["summary"]
                    # Take only first section (## Суть)
                    lines = text.split("\n")
                    gist_lines = []
                    for line in lines:
                        if line.strip().startswith("## ") and gist_lines:
                            break
                        gist_lines.append(line)
                    quick = "\n".join(gist_lines).strip()
                    full["summary"] = quick
                result = full
            else:
                raise ValueError(f"Unknown tool: {name}")

            text_out = json.dumps(result, ensure_ascii=False, indent=2)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text_out}]
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    if method == "notifications/initialized":
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            req = json.loads(line.strip())
            resp = handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except Exception as e:
            sys.stderr.write(f"Server error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
