#!/usr/bin/env python3
"""
Nightly Granola archive script.
Reads from local Granola cache and falls back to Granola API for recent meetings
whose notes are not yet stored locally. Sends a Slack DM on failure.
"""

import gzip
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

# --- Config ---
ARCHIVE_DIR = Path("/Users/stephaniebutler/Library/CloudStorage/GoogleDrive-sbutler@kiddom.co/My Drive/Granola Notes")
LOOKBACK_DAYS = 2



def slack_alert(message):
    """Placeholder — Slack alerting not yet configured."""
    pass


# --- Granola cache ---

def _find_cache_file():
    granola_dir = Path.home() / "Library/Application Support/Granola"
    candidates = sorted(granola_dir.glob("cache-v*.json"), key=lambda p: int(re.search(r"v(\d+)", p.name).group(1)))
    if not candidates:
        raise FileNotFoundError(f"No cache-v*.json found in {granola_dir}")
    return candidates[-1]


CACHE_FILE = _find_cache_file()


# --- Granola API ---

def _load_api_token():
    import time
    sup_path = Path.home() / "Library/Application Support/Granola/supabase.json"
    try:
        sup = json.loads(sup_path.read_text())
        workos = json.loads(sup["workos_tokens"])
        token = workos["access_token"]
        obtained_at_ms = workos.get("obtained_at", 0)
        expires_in = workos.get("expires_in", 0)
        expires_at_ms = obtained_at_ms + expires_in * 1000
        if time.time() * 1000 > expires_at_ms:
            return None, "Granola API token is expired — open Granola to refresh it"
        return token, None
    except Exception as e:
        return None, f"Could not load Granola API token: {e}"


API_TOKEN, API_TOKEN_ERROR = _load_api_token()


def call_api(endpoint, payload):
    """POST to Granola API, return parsed JSON or None on failure."""
    if not API_TOKEN:
        return None
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.granola.ai/v1/{endpoint}",
        data=data,
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)
    except Exception as e:
        print(f"  [warn] API call {endpoint} failed: {e}")
        return None


# --- HTML/Prosemirror helpers ---

class _HTMLToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
        self._current = []
        self._list_depth = 0
        self._in_li = False

    def _flush(self):
        text = "".join(self._current).strip()
        self._current = []
        return text

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush()
        elif tag == "li":
            self._in_li = True
            self._current = []
        elif tag == "ul":
            self._list_depth += 1
        elif tag == "p":
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4"):
            level = int(tag[1])
            text = self._flush()
            if text:
                self.lines.append(f"{'#' * level} {text}")
        elif tag == "li":
            text = self._flush()
            if text:
                indent = "  " * (self._list_depth - 1)
                self.lines.append(f"{indent}- {text}")
            self._in_li = False
        elif tag == "ul":
            self._list_depth = max(0, self._list_depth - 1)
        elif tag == "p":
            text = self._flush()
            if text:
                self.lines.append(text)

    def handle_data(self, data):
        self._current.append(html.unescape(data))

    def get_markdown(self):
        text = self._flush()
        if text:
            self.lines.append(text)
        return "\n".join(self.lines).strip()


def html_to_markdown(html_str):
    if not html_str:
        return ""
    parser = _HTMLToMarkdown()
    parser.feed(html_str)
    return parser.get_markdown()


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
        return "\n".join(prosemirror_to_markdown(c, depth) for c in children)
    elif node_type == "listItem":
        parts = []
        for child in children:
            if child.get("type") == "paragraph":
                text = "".join(prosemirror_to_markdown(c) for c in child.get("content", []))
                parts.append(f"{indent}- {text}")
            elif child.get("type") == "bulletList":
                parts.append(prosemirror_to_markdown(child, depth + 1))
        return "\n".join(parts)
    elif node_type == "text":
        return node.get("text", "")
    elif node_type == "horizontalRule":
        return "---"
    return ""


def has_text_content(node):
    if not isinstance(node, dict):
        return False
    if node.get("type") == "text" and node.get("text", "").strip():
        return True
    for child in (node.get("content") or []):
        if has_text_content(child):
            return True
    return False


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


# --- Main ---

def main():
    today = datetime.now(timezone.utc).date()
    cutoff_date = today - timedelta(days=LOOKBACK_DAYS)
    warnings = []

    if API_TOKEN_ERROR:
        print(f"  [warn] {API_TOKEN_ERROR}")
        warnings.append(API_TOKEN_ERROR)

    with open(CACHE_FILE) as f:
        raw = json.load(f)
    state = raw["cache"]["state"]
    documents = state.get("documents", {})
    transcripts = state.get("transcripts", {})

    synced = 0
    empty_notes = []

    for doc_id, doc in documents.items():
        if doc.get("deleted_at"):
            continue

        title = doc.get("title")
        if not title:
            continue

        date_str = doc.get("created_at") or doc.get("updated_at")
        doc_date = parse_date(date_str)
        if not doc_date or doc_date.date() < cutoff_date:
            continue

        folder_name = doc_date.strftime("%Y-%m-%d")
        slug = slugify(title)
        folder = ARCHIVE_DIR / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        # --- Notes ---
        notes_doc = doc.get("notes")
        ai_notes = prosemirror_to_markdown(notes_doc) if notes_doc and has_text_content(notes_doc) else ""
        raw_notes = doc.get("notes_markdown") or ""

        if not ai_notes and not raw_notes.strip():
            panels = call_api("get-document-panels", {"document_id": doc_id})
            if panels:
                parts = []
                for panel in panels:
                    panel_title = panel.get("title", "")
                    content = panel.get("content", "")
                    if isinstance(content, dict):
                        md = prosemirror_to_markdown(content)
                    elif isinstance(content, str):
                        md = html_to_markdown(content)
                    else:
                        md = ""
                    if md:
                        parts.append(f"## {panel_title}\n\n{md}" if panel_title else md)
                ai_notes = "\n\n".join(parts)

        if not ai_notes and not raw_notes.strip():
            empty_notes.append(f"{folder_name}/{title}")

        notes_content = f"# {title}\n\n"
        notes_content += f"**Date:** {doc_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        if ai_notes:
            notes_content += ai_notes + "\n"
        if raw_notes.strip():
            notes_content += f"\n## My Notes\n\n{raw_notes}\n"
        if not ai_notes and not raw_notes.strip():
            notes_content += "_No notes available._\n"

        (folder / f"{slug}-notes.md").write_text(notes_content, encoding="utf-8")

        # --- Transcript ---
        segments = transcripts.get(doc_id, [])
        if not segments:
            api_segs = call_api("get-document-transcript", {"document_id": doc_id})
            if api_segs:
                segments = api_segs

        transcript_content = f"# {title} — Transcript\n\n"
        transcript_content += f"**Date:** {doc_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        transcript_content += format_transcript(segments)
        (folder / f"{slug}-transcript.md").write_text(transcript_content, encoding="utf-8")

        print(f"  Saved: {folder_name}/{slug}")
        synced += 1

    print(f"\nDone. Synced {synced} meetings.")

    # --- Health check ---
    if empty_notes:
        msg = f":warning: *Granola sync:* {len(empty_notes)} meeting(s) saved with no notes (API may have changed or notes not yet generated):\n"
        msg += "\n".join(f"  • {m}" for m in empty_notes)
        print(f"\n[alert] {msg}")
        slack_alert(msg)

    if warnings:
        for w in warnings:
            msg = f":warning: *Granola sync warning:* {w}"
            print(f"\n[alert] {msg}")
            slack_alert(msg)

    if synced == 0:
        msg = ":warning: *Granola sync:* ran but found 0 meetings to archive — cache format may have changed"
        print(f"\n[alert] {msg}")
        slack_alert(msg)


if __name__ == "__main__":
    main()
