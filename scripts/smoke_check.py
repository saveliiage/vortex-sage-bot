#!/usr/bin/env python3
"""Lightweight smoke checks for Vortex.

Runs without real bot tokens or third-party Python packages where possible.
Focuses on regressions that broke production: callback routing and platform routing.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_source(rel: str, name: str) -> str:
    source = _read(rel)
    tree = ast.parse(source, filename=rel)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {rel}:{name}")


def assert_callback_routing_is_specific() -> None:
    bot = _read("bot.py")
    music = 'CallbackQueryHandler(handle_music_download, pattern=r"^music_"'
    media = 'CallbackQueryHandler(\n        handle_callback,\n        pattern=r"^(dl_video|dl_audio|summarize|circle|thumbnail|info|save_yes|save_no)$"'
    assert music in bot, "music callback must be registered with anchored ^music_ pattern"
    assert media in bot, "generic media callback must be constrained to known media/save actions"
    assert bot.find(music) < bot.find(media), "music callback must be registered before generic callback"


def assert_platform_router_used_for_instagram_downloads() -> None:
    video = _function_source("handlers/download.py", "handle_download_video")
    audio = _function_source("handlers/download.py", "handle_download_audio")
    circle = _function_source("handlers/download.py", "handle_circle")

    assert "download_video(url)" in video, "video downloads must use core.downloader.download_video platform router"
    assert "run_ytdlp(" not in video and "_ytdlp_download_with_progress" not in video, (
        "handle_download_video must not call yt-dlp directly; Instagram/TikTok need platform router"
    )

    assert "download_audio(url)" in audio, "audio downloads must use core.downloader.download_audio platform router"
    assert "run_ytdlp(" not in audio, "handle_download_audio must not call yt-dlp directly"

    assert "download_video(url)" in circle, "circle downloads must use platform router before ffmpeg conversion"
    assert "_ytdlp_download_with_progress" not in circle, "handle_circle must not call yt-dlp directly"


def assert_subtitle_first_flow_exists() -> None:
    download = _read("handlers/download.py")
    assert "--write-auto-sub" in download, "YouTube summary must use auto subtitles"
    assert "parse_vtt" in download, "YouTube summary must parse VTT subtitles"


def main() -> None:
    assert_callback_routing_is_specific()
    assert_platform_router_used_for_instagram_downloads()
    assert_subtitle_first_flow_exists()
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
