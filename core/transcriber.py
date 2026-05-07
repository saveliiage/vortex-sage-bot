"""Speech-to-text via faster-whisper."""

import os
import json
from pathlib import Path
from faster_whisper import WhisperModel

from config import WHISPER_MODEL

# Global model cache — load once, reuse across calls
_model = None


def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_path: str) -> dict:
    """Transcribe audio file. Returns dict with full text + segments with timestamps."""
    model = get_model()
    segments, info = model.transcribe(audio_path, beam_size=5)

    result = {
        "language": info.language,
        "duration": round(info.duration, 2),
        "full_text": "",
        "segments": [],
    }

    text_parts = []
    for seg in segments:
        result["segments"].append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        text_parts.append(seg.text.strip())

    result["full_text"] = " ".join(text_parts)
    return result


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS."""
    secs = int(seconds)
    h, m = divmod(secs, 3600)
    m, s = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_transcript(segments: list, include_timestamps: bool = True) -> str:
    """Format segments into readable transcript text."""
    lines = []
    for seg in segments:
        ts = format_timestamp(seg["start"])
        if include_timestamps:
            lines.append(f"[{ts}] {seg['text']}")
        else:
            lines.append(seg["text"])
    return "\n".join(lines)


def extract_audio_from_video(video_path: str, output_path: str = None) -> str:
    """Extract audio from video using ffmpeg. Returns path to audio file."""
    import subprocess

    if not output_path:
        output_path = video_path.rsplit(".", 1)[0] + ".wav"

    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path,
         "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1",
         output_path],
        capture_output=True,
        timeout=300,
    )
    return output_path if os.path.exists(output_path) else ""