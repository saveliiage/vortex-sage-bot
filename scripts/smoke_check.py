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
    media = 'CallbackQueryHandler(\n        handle_callback,\n        pattern=r"^(dl_video|dl_audio|summarize|circle|thumbnail|info)$"'
    assert music in bot, "music callback must be registered with anchored ^music_ pattern"
    assert media in bot, "generic media callback must be constrained to known media actions"
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


def assert_tiktok_routing_prefers_ytdlp() -> None:
    """TikTok goes through yt-dlp first (2026.08+ solves the JS challenge); Apify is fallback only."""
    downloader = _read("core/downloader.py")
    tiktok = _read("core/tiktok.py")

    assert "from core import instagram, tiktok, apify_tiktok" in downloader, (
        "core.downloader must import the yt-dlp tiktok module alongside the Apify fallback"
    )
    assert "_tiktok_or_fallback(" in downloader, "TikTok platform branches must route through the fallback wrapper"
    assert "YT_COOKIES_ARGS" not in tiktok, (
        "core.tiktok must not pass the YouTube cookie jar — it also holds TikTok session cookies "
        "and TikTok answers 403 when they are sent"
    )
    assert 'vcodec^=h264' in tiktok, "TikTok download must prefer H.264 — Telegram cannot play bytevc1/h265"


def assert_subtitle_first_flow_exists() -> None:
    download = _read("handlers/download.py")
    summarizer = _read("core/summarizer.py")
    assert "from core.summarizer import summarize_video" in download, (
        "summary handler must call core.summarizer.summarize_video"
    )
    assert "summarize_video(" in download, "summary handler must call core.summarizer.summarize_video"
    assert "from core.subtitles_json3 import fetch_transcript" in summarizer, (
        "summarizer must fetch subtitles through core.subtitles_json3.fetch_transcript"
    )
    assert "fetch_transcript(url, languages=lang)" in summarizer, (
        "summarizer must fetch subtitles through core.subtitles_json3.fetch_transcript"
    )


def assert_downloads_go_anonymous_first() -> None:
    """A stale cookie jar must not break downloads: run anonymously, retry with the jar.

    Regression this pins: the jar was prepended to every yt-dlp run, so an expired YouTube
    session turned every download into `HTTP Error 403: Forbidden` on videoplayback.
    """
    runner = _read("core/ytdlp.py")
    downloader = _read("core/downloader.py")
    handler = _read("handlers/download.py")

    assert "def cookie_profiles() -> list:" in runner, (
        "core.ytdlp must own the anonymous-first cookie profiles"
    )
    assert "def cookie_related(error: str) -> bool:" in runner, (
        "core.ytdlp must own the cookie-error classifier that gates the retry"
    )
    assert "ytdlp.run(" in downloader, "core.downloader must run yt-dlp through core.ytdlp.run"
    assert "ytdlp.cookie_profiles()" in handler, (
        "the progress download path must share the same anonymous-first fallback"
    )
    assert "_YT_COOKIES_ARG = YT_COOKIES_ARGS" not in downloader, (
        "cookie args must not be hard-wired into the yt-dlp prefix"
    )


def main() -> None:
    assert_callback_routing_is_specific()
    assert_platform_router_used_for_instagram_downloads()
    assert_tiktok_routing_prefers_ytdlp()
    assert_subtitle_first_flow_exists()
    assert_downloads_go_anonymous_first()
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
