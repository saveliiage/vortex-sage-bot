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
    """Save transcript and summary to Obsidian vault. Returns path."""

    safe_title = _sanitize_filename(title)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str} — {safe_title}.md"
    filepath = os.path.join(TRANSCRIPTS_DIR, filename)

    # Build content
    lines = []
    lines.append(f"# Транскрипт: {title}\n")
    lines.append(f"**Источник:** {source_url}")
    lines.append(f"**Дата:** {date_str}")
    lines.append(f"**Длительность:** {duration} сек")
    lines.append(f"**Платформа:** {platform}")
    lines.append("")

    if summary_data and summary_data.get("success"):
        if summary_data.get("summary"):
            lines.append("## Саммари")
            lines.append(summary_data["summary"])
            lines.append("")
        if summary_data.get("key_points"):
            lines.append("## Ключевые темы")
            for pt in summary_data["key_points"]:
                lines.append(f"- {pt}")
            lines.append("")
        if summary_data.get("sections"):
            lines.append("## Разделы")
            for sec in summary_data["sections"]:
                lines.append(f"- **{sec.get('time', '??')}** — {sec.get('title', '')}")
                if sec.get("description"):
                    lines.append(f"  — {sec['description']}")
            lines.append("")

    lines.append("## Полный транскрипт")
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