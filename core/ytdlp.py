"""Single entry point for yt-dlp runs.

Every run goes out anonymously first and only retries with the cookie jar when the failure
looks like a cookie or bot-check problem. A stale or half-dead jar then costs one extra
attempt instead of breaking downloads that work fine without it, the classic symptom being
`HTTP Error 403: Forbidden` on the googlevideo videoplayback URL.
"""

import logging
import os
import subprocess

from config import YT_COOKIES_EXTRA_ARGS, YT_COOKIES_JAR_ARGS, YT_DLP_BIN

log = logging.getLogger(__name__)

BASE_ARGS = ["--no-playlist", "--no-warnings"]

# Failures that mean "try the other cookie profile", not "give up".
_COOKIE_HINTS = (
    "403",
    "forbidden",
    "sign in",
    "not a bot",
    "cookies",
    "login required",
    "confirm your age",
    "age-restricted",
    "members-only",
    "format is not available",
    "unable to download",
    "unable to extract",
    "content isn't available",
)


def cookie_related(error: str) -> bool:
    """True when a yt-dlp error looks like a cookie or bot-check problem."""
    text = (error or "").lower()
    return any(hint in text for hint in _COOKIE_HINTS)


def cookie_profiles() -> list:
    """Cookie profiles to try in order. Anonymous first, the jar only as a retry."""
    if YT_COOKIES_JAR_ARGS:
        return [[], list(YT_COOKIES_JAR_ARGS)]
    return [[]]


def build_cmd(args: list, profile: list | None = None) -> list:
    """Full yt-dlp argv for one cookie profile (`[]` means anonymous)."""
    return (
        [YT_DLP_BIN]
        + BASE_ARGS
        + list(profile or [])
        + list(YT_COOKIES_EXTRA_ARGS)
        + list(args)
    )


def run(args: list, want_path: bool = False, timeout: int = 600, cwd: str | None = None) -> dict:
    """Run yt-dlp synchronously with the anonymous-first cookie fallback.

    Returns {success, output?, path?, error?}. The jar is only tried when the anonymous
    attempt died for a cookie-related reason, so a broken jar cannot break a working download.
    """
    profiles = cookie_profiles()
    result = {"success": False, "error": "yt-dlp failed"}
    for index, profile in enumerate(profiles):
        result = _exec(build_cmd(args, profile), want_path=want_path, timeout=timeout, cwd=cwd)
        if result.get("success"):
            return result
        if index + 1 < len(profiles) and cookie_related(result.get("error", "")):
            log.warning(
                "yt-dlp anonymous attempt failed (%s), retrying with the cookie jar",
                result.get("error"),
            )
            continue
        return result
    return result


def _exec(cmd: list, want_path: bool, timeout: int, cwd: str | None) -> dict:
    """One yt-dlp invocation. `want_path` requires `--print after_move:filepath` in args."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"yt-dlp timeout ({timeout}s)"}
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
