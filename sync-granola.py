#!/usr/bin/env python3
"""
Nightly Granola archive script.
Reads from local Granola cache and writes notes + transcripts to Google Drive.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

def _find_cache_file():
    granola_dir = Path.home() / "Library/Application Support/Granola"
    candidates = sorted(granola_dir.glob("cache-v*.json"), key=lambda p: int(re.search(r"v(\d+)", p.name).group(1)))
    if not candidates:
        raise FileNotFoundError(f"No cache-v*.json found in {granola_dir}")
    return candidates[-1]

CACHE_FILE = _find_cache_file()
ARCHIVE_DIR = Path(os.environ.get(
    "GRANOLA_ARCHIVE_DIR",
    str(Path.home() / "Documents/Granola Notes"),
))
LOOKBACK_DAYS = 2


def slugify(title):
    title = title.lower().strip()
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"[\s_]+", "-", title)
    title = re.sub(r"-+", "-", title)
    return title[:80]


def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


def prosemirror_to_markdown(node, depth=0):
    """Recursively convert a Prosemirror JSON node to markdown."""
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type", "")
    children = node.get("content", []) or []
    indent = "  " * depth

    if node_type == "doc":
        return "\n".join(prosemirror_to_markdown(c, depth) for c in children).strip()

    elif node_type == "heading":
        level = node.get("attrs", {}).get("level", 3)
        text = "".join(prosemirror_to_markdown(c, depth) for c in children)
        return f"{'#' * level} {text}"

    elif node_type == "paragraph":
        text = "".join(prosemirror_to_markdown(c, depth) for c in children)
        return text if text.strip() else ""

    elif node_type == "bulletList":
        items = [prosemirror_to_markdown(c, depth) for c in children]
        return "\n".join(items)

    elif node_type == "listItem":
        parts = []
        for i, child in enumerate(children):
            child_type = child.get("type", "")
            if child_type == "paragraph":
                text = "".join(prosemirror_to_markdown(c) for c in child.get("content", []))
                parts.append(f"{indent}- {text}")
            elif child_type == "bulletList":
                parts.append(prosemirror_to_markdown(child, depth + 1))
        return "\n".join(parts)

    elif node_type == "text":
        return node.get("text", "")

    elif node_type == "horizontalRule":
        return "---"

    return ""


def format_notes(panel_dict):
    """Extract and convert AI notes from documentPanels dict."""
    parts = []
    for panel_id, panel in panel_dict.items():
        content = panel.get("content")
        if not isinstance(content, dict) or not content.get("content"):
            continue
        title = panel.get("title", "")
        if title:
            parts.append(f"## {title}\n")
        parts.append(prosemirror_to_markdown(content))
    return "\n\n".join(parts).strip()


def format_transcript(segments):
    if not segments:
        return "_No transcript available._"
    lines = []
    for seg in segments:
        if not seg.get("is_final"):
            continue
        text = seg.get("text", "").strip()
        if not text:
            continue
        source = seg.get("source", "")
        ts = seg.get("start_timestamp", "")
        time_label = ""
        if ts:
            dt = parse_date(ts)
            if dt:
                time_label = dt.strftime("%H:%M:%S") + " "
        speaker = "System" if source == "system" else "Microphone"
        lines.append(f"**[{time_label}{speaker}]** {text}")
    return "\n\n".join(lines) if lines else "_No transcript available._"


def main():
    today = datetime.now(timezone.utc).date()
    cutoff_date = today - timedelta(days=LOOKBACK_DAYS)

    with open(CACHE_FILE) as f:
        raw = json.load(f)
    state = raw["cache"]["state"]
    documents = state.get("documents", {})
    transcripts = state.get("transcripts", {})

    synced = 0

    for doc_id, doc in documents.items():
        if doc.get("deleted_at"):
            continue

        date_str = doc.get("created_at") or doc.get("updated_at")
        doc_date = parse_date(date_str)
        if not doc_date or doc_date.date() < cutoff_date:
            continue

        title = doc.get("title") or "Untitled Meeting"
        folder_name = doc_date.strftime("%Y-%m-%d")
        slug = slugify(title)

        folder = ARCHIVE_DIR / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        # --- Notes file ---
        notes_doc = doc.get("notes")
        ai_notes = prosemirror_to_markdown(notes_doc) if notes_doc else ""
        raw_notes = doc.get("notes_markdown") or ""

        notes_content = f"# {title}\n\n"
        notes_content += f"**Date:** {doc_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        if ai_notes:
            notes_content += ai_notes + "\n"
        if raw_notes:
            notes_content += f"\n## My Notes\n\n{raw_notes}\n"
        if not ai_notes and not raw_notes:
            notes_content += "_No notes available._\n"

        notes_path = folder / f"{slug}-notes.md"
        notes_path.write_text(notes_content, encoding="utf-8")

        # --- Transcript file ---
        segments = transcripts.get(doc_id, [])
        transcript_content = f"# {title} — Transcript\n\n"
        transcript_content += f"**Date:** {doc_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        transcript_content += format_transcript(segments)

        transcript_path = folder / f"{slug}-transcript.md"
        transcript_path.write_text(transcript_content, encoding="utf-8")

        print(f"  Saved: {folder_name}/{slug}")
        synced += 1

    print(f"\nDone. Synced {synced} meetings.")


if __name__ == "__main__":
    main()
