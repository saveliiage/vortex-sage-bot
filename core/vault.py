"""Obsidian vault writer — save transcripts and summaries."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from config import VAULT_PATH, TRANSCRIPTS_DIR


def _sanitize_filename(name: str) -> str:
    """Remove chars that break filenames."""
    forbidden = r'<>:"/\|?*'
    for c in forbidden:
        name = name.replace(c, "")
    return name.strip()[:80]


def save_transcript(
    title: str,
    source_url: str,
    platform: str,
    duration: int,
    full_text: str,
    summary_data: dict = None,
) -> str:
    """Save transcript and summary to Obsidian vault. Returns filesystem path."""

    safe_title = _sanitize_filename(title)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str} — {safe_title}.md"
    filepath = os.path.join(TRANSCRIPTS_DIR, filename)

    # Duration
    dur_str = f"{duration // 60} мин" if duration else "?"

    # Build content
    lines = []
    lines.append("---")
    lines.append(f"title: \"{title}\"")
    lines.append(f"source: {source_url}")
    lines.append(f"date: {date_str}")
    lines.append(f"duration: {dur_str}")
    lines.append(f"platform: {platform}")
    lines.append("type: transcript")
    lines.append("---")
    lines.append("")

    # Summary
    lines.append(f"# {title}")
    lines.append("")
    if summary_data and summary_data.get("success"):
        summary_text = summary_data.get("summary", "")
        if summary_text:
            lines.append("## Саммари")
            lines.append(summary_text)
            lines.append("")
    else:
        lines.append("*(Саммари недоступно)*")
        lines.append("")

    # Full transcript
    lines.append("## Транскрипт")
    lines.append("```")
    lines.append(full_text)
    lines.append("```")

    content = "\n".join(lines)

    # Write file
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


def git_push(filepath: str) -> dict:
    """Git add + commit + push the new transcript."""
    try:
        # Git add
        subprocess.run(
            ["git", "add", filepath],
            cwd=VAULT_PATH,
            capture_output=True,
            timeout=30,
        )
        # Git commit
        filename = os.path.basename(filepath)
        subprocess.run(
            ["git", "commit", "-m", f"vortex: add transcript — {filename}"],
            cwd=VAULT_PATH,
            capture_output=True,
            timeout=30,
        )
        # Git push
        result = subprocess.run(
            ["git", "push"],
            cwd=VAULT_PATH,
            capture_output=True,
            timeout=60,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout.decode() + result.stderr.decode(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
