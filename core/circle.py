"""Video circle converter — turn any video into Telegram video note (640x640)."""

import os
import subprocess
import tempfile
from pathlib import Path


def convert_to_circle(input_path: str, duration: int = 60) -> dict:
    """
    Convert video to square 640x640 video note format.
    Returns dict with 'path' to output file.
    """
    output_fd, output_path = tempfile.mkstemp(suffix=".mp4")
    os.close(output_fd)

    duration = min(duration or 60, 60)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", "scale=640:640:force_original_aspect_ratio=increase,crop=640:640",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(duration),
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        return {
            "success": False,
            "error": f"ffmpeg error: {result.stderr.strip()[:200]}",
        }

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return {"success": False, "error": "Output file is empty"}

    return {
        "success": True,
        "path": output_path,
    }