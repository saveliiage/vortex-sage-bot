"""Audio to voice note converter — any audio → OGG/Opus for Telegram send_voice."""

import os
import subprocess
import tempfile


def convert_to_voice(input_path: str) -> dict:
    """
    Convert any audio file to OGG/Opus suitable for Telegram voice note.
    Returns dict with 'path' to output .ogg file.
    """
    output_fd, output_path = tempfile.mkstemp(suffix=".ogg")
    os.close(output_fd)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:a", "libopus",
        "-b:a", "32k",
        "-vbr", "on",
        "-application", "voip",
        "-frame_duration", "20",
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
