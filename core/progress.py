"""Async runner with progress reporting for yt-dlp and ffmpeg."""

import asyncio
import os
import re
import logging

log = logging.getLogger(__name__)

# ── Progress bar generation ──────────────────────────────────────────────────

FULL = "🟩"
EMPTY = "⬜"


def _pct_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return FULL * filled + EMPTY * (width - filled)


# ── yt-dlp progress parser ──────────────────────────────────────────────────

# [download]  45.2% of ~11.37MiB at  3.64MiB/s ETA 00:01
# [download] 100.0% of  11.37MiB in 00:03
_RE_YT_PROGRESS = re.compile(r"\[download\]\s+(\d+\.?\d*)%")


def _parse_yt_progress(line: str) -> float | None:
    m = _RE_YT_PROGRESS.search(line)
    if m:
        return float(m.group(1))
    return None


# ── ffmpeg progress parser ──────────────────────────────────────────────────

# frame=  186 fps= 59 q=29.0 size=   184KiB time=00:00:06.16 ...
_RE_FF_TIME = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def _parse_ffmpeg_progress(line: str, duration_sec: float) -> float | None:
    m = _RE_FF_TIME.search(line)
    if m:
        h, m_, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        current = h * 3600 + m_ * 60 + s
        if duration_sec > 0:
            return min(current / duration_sec * 100, 99.9)
    return None


# ── Public API ───────────────────────────────────────────────────────────────


async def run_ytdlp(
    args: list,
    progress_callback=None,
    label: str = "⬇️ Скачиваю",
) -> dict:
    """
    Run yt-dlp asynchronously with optional progress callback.
    `progress_callback(pct: float, text: str)` is called every ~5% change.
    Returns same shape as sync `_run_ytdlp`.
    """
    cmd = args if args[0] == "/opt/vortex/venv/bin/yt-dlp" else ["/opt/vortex/venv/bin/yt-dlp"] + args
    last_pct = -1

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_lines = []
    stderr_lines = []

    async def _read_stream(stream, is_stderr: bool):
        nonlocal last_pct
        while True:
            line_bytes = await stream.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if is_stderr:
                stderr_lines.append(line)
                pct = _parse_yt_progress(line)
                if pct is not None and abs(pct - last_pct) >= 5:
                    last_pct = pct
                    if progress_callback:
                        bar = _pct_bar(pct)
                        await progress_callback(f"{label} {bar} {pct:.0f}%")
            else:
                stdout_lines.append(line)

    await asyncio.gather(
        _read_stream(proc.stdout, False),
        _read_stream(proc.stderr, True),
    )

    await proc.wait()
    stdout = "\n".join(stdout_lines)
    stderr = "\n".join(stderr_lines)

    if proc.returncode != 0:
        err = stderr.strip().splitlines()[-1] if stderr.strip() else "yt-dlp failed"
        return {"success": False, "error": err}

    return {"success": True, "output": stdout, "stderr": stderr}


async def run_ffmpeg_with_progress(
    input_path: str,
    output_path: str,
    filters: str,
    duration_sec: float = 60,
    extra_args: list = None,
    progress_callback=None,
    label: str = "🔄 Конвертирую",
) -> dict:
    """
    Run ffmpeg asynchronously with progress parsing.
    `progress_callback(pct, text)` called every ~10%.
    """
    cmd = ["ffmpeg", "-y", "-i", input_path]
    if filters:
        cmd += ["-vf", filters]
    if extra_args:
        cmd += extra_args
    cmd += ["-progress", "pipe:1", output_path]

    last_pct = -1

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _read_stdout():
        nonlocal last_pct
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            pct = _parse_ffmpeg_progress(text, duration_sec)
            if pct is not None and abs(pct - last_pct) >= 10:
                last_pct = pct
                if progress_callback:
                    bar = _pct_bar(pct)
                    await progress_callback(f"{label} {bar} {pct:.0f}%")

    async def _drain_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break

    await asyncio.gather(_read_stdout(), _drain_stderr())
    await proc.wait()

    if proc.returncode != 0 or not os.path.exists(output_path):
        return {"success": False, "error": f"ffmpeg exit code {proc.returncode}"}
    if os.path.getsize(output_path) == 0:
        return {"success": False, "error": "Output file is empty"}

    return {"success": True, "path": output_path}