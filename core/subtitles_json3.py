"""YouTube subtitle fetcher via yt-dlp JSON3 format.
Faster and cleaner than youtube-transcript-api or VTT/SRT parsing.
No external deps beyond yt-dlp."""

import json
import re
import subprocess
import tempfile
from pathlib import Path

YT_DLP = "/opt/vortex/venv/bin/yt-dlp"


def _run(cmd: list, cwd=None, timeout=120) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:500])
    return r.stdout


def _extract_video_id(url: str) -> str:
    m = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", url)
    if not m:
        raise ValueError(f"Cannot extract video ID from {url}")
    return m.group(1)


def _fetch_info(url: str) -> dict:
    try:
        out = _run([YT_DLP, "--dump-json", "--skip-download", url], timeout=60)
        data = json.loads(out.splitlines()[0])
        return {
            "title": data.get("title", "Unknown"),
            "duration": data.get("duration", 0),
            "uploader": data.get("uploader", "Unknown"),
            "video_id": data.get("id", ""),
        }
    except Exception:
        return {"title": "Unknown", "duration": 0, "uploader": "Unknown", "video_id": ""}


def download_json3(url: str, languages: str = "ru-orig,ru,en", workdir: Path = None) -> Path:
    """Download YouTube auto-subtitles in JSON3 format. Returns path to file."""
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="vortex_subs_"))

    base_cmd = [
        YT_DLP,
        "--cookies-from-browser", "chromium",
        "--skip-download",
        "--write-auto-subs",
        f"--sub-langs={languages}",
        "--sub-format", "json3",
        "--output", str(workdir / "subs"),
        url,
    ]
    for extra in [["--remote-components", "ejs:github"], []]:
        cmd = [base_cmd[0]] + extra + base_cmd[1:]
        try:
            _run(cmd, cwd=str(workdir))
            break
        except RuntimeError:
            candidates = list(workdir.glob("subs.*.json3"))
            if candidates:
                break
            if not extra:
                raise RuntimeError(f"yt-dlp failed to download subtitles for {url}")
    else:
        raise RuntimeError("yt-dlp failed")

    candidates = list(workdir.glob("subs.*.json3"))
    if not candidates:
        raise RuntimeError("No subtitles available. Video may have subtitles disabled.")

    pref_order = ["ru-orig", "ru", "en"]
    for pref in pref_order:
        for c in candidates:
            if pref in c.name:
                return c
    return candidates[0]


def parse_json3(path: Path) -> list:
    """Parse YouTube json3 into list of {'time': 'MM:SS', 'text': str} blocks."""
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = []
    for ev in data.get("events", []):
        t = ev.get("tStartMs", 0)
        segs = ev.get("segs", [])
        words = [s.get("utf8", "") for s in segs if s.get("utf8")]
        text = "".join(words).strip()
        if text:
            blocks.append({"time": f"{t // 1000 // 60:02d}:{t // 1000 % 60:02d}", "text": text})
    return blocks


def deduplicate(blocks: list) -> list:
    """Remove exact duplicate blocks, merge very short ones into previous."""
    clean, seen = [], set()
    for b in blocks:
        t = b["text"]
        if t in seen:
            continue
        seen.add(t)
        if len(t) < 8 and clean:
            clean[-1]["text"] += " " + t
            continue
        clean.append(dict(b))
    return clean


def format_transcript(blocks: list, stamp_every: int = 45) -> str:
    """Format blocks into clean text with timestamps every N seconds."""
    out, last = [], -999
    for b in blocks:
        m, s = map(int, b["time"].split(":"))
        secs = m * 60 + s
        if secs - last >= stamp_every:
            out.append(f"\n[{b['time']}] {b['text']}")
            last = secs
        else:
            out.append(b["text"])
    return "\n".join(out)


def fetch_transcript(url: str, languages: str = "ru-orig,ru,en") -> dict:
    """High-level: fetch + parse + clean + format. Returns dict with metadata."""
    info = _fetch_info(url)
    with tempfile.TemporaryDirectory() as tmpdir:
        wd = Path(tmpdir)
        sub_path = download_json3(url, languages, wd)
        blocks = deduplicate(parse_json3(sub_path))
        transcript = format_transcript(blocks)
        return {
            "success": True,
            "title": info["title"],
            "duration": info["duration"],
            "uploader": info["uploader"],
            "video_id": info["video_id"],
            "language": sub_path.name.split(".")[-2] if "." in sub_path.name else "unknown",
            "blocks": len(blocks),
            "chars": len(transcript),
            "text": transcript,
        }
