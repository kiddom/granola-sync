#!/usr/bin/env python3
"""
Nightly Granola archive script.
Reads meeting data from the Granola API. Token auto-refreshed when expired.
"""

import gzip
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

# --- Config ---
_default_archive = Path.home() / "Documents" / "Granola Notes"
ARCHIVE_DIR = Path(os.environ.get("GRANOLA_ARCHIVE_DIR", str(_default_archive)))
LOOKBACK_DAYS = 2
ACCOUNTS_FILE = Path.home() / "Library/Application Support/Granola/stored-accounts.json"
TOKEN_CACHE_FILE = Path.home() / ".granola-sync-token.json"
WORKOS_CLIENT_ID = "client_01JZJ0XBDAT8PHJWQY09Y0VD61"
WORKOS_AUTH_URL = "https://auth.granola.ai/user_management/authenticate"
API_BASE = "https://api.granola.ai/v1"


def slack_alert(message):
    """Placeholder — Slack alerting not yet configured."""
    pass


# --- Token management ---

def _read_accounts_tokens():
    """Return (access_token, refresh_token, obtained_at_ms) from stored-accounts.json."""
    try:
        raw = json.loads(ACCOUNTS_FILE.read_text())
        accounts = json.loads(raw["accounts"])
        if not accounts:
            return None, None, 0
        tokens = json.loads(accounts[0]["tokens"])
        return tokens.get("access_token"), tokens.get("refresh_token"), tokens.get("obtained_at", 0)
    except Exception:
        return None, None, 0


def _read_cache_tokens():
    """Return (access_token, refresh_token, obtained_at_ms) from local token cache."""
    try:
        if TOKEN_CACHE_FILE.exists():
            data = json.loads(TOKEN_CACHE_FILE.read_text())
            return data.get("access_token"), data.get("refresh_token"), data.get("obtained_at", 0)
    except Exception:
        pass
    return None, None, 0


def _save_token_cache(access_token, refresh_token):
    try:
        TOKEN_CACHE_FILE.write_text(json.dumps({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "obtained_at": int(time.time() * 1000),
        }))
    except Exception:
        pass


def _is_expired(obtained_at_ms, expires_in_s=21599, buffer_s=300):
    """True if token expires within buffer_s seconds."""
    return time.time() * 1000 > obtained_at_ms + (expires_in_s - buffer_s) * 1000


def _do_refresh(refresh_token):
    """Call WorkOS refresh endpoint. Returns (access_token, refresh_token) or (None, None)."""
    payload = {
        "grant_type": "refresh_token",
        "client_id": WORKOS_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    req = urllib.request.Request(
        WORKOS_AUTH_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        return result.get("access_token"), result.get("refresh_token")
    except Exception as e:
        print(f"  [warn] Token refresh failed: {e}")
        return None, None


def load_api_token():
    """
    Return (token, error_string). Strategy:
    1. Local cache — if fresh, use it.
    2. stored-accounts.json — if fresh, use it.
    3. Either source has a refresh_token — try to refresh.
    """
    c_tok, c_ref, c_at = _read_cache_tokens()
    if c_tok and c_at and not _is_expired(c_at):
        return c_tok, None

    a_tok, a_ref, a_at = _read_accounts_tokens()
    if a_tok and a_at and not _is_expired(a_at):
        return a_tok, None

    refresh = a_ref or c_ref
    if refresh:
        new_tok, new_ref = _do_refresh(refresh)
        if new_tok:
            _save_token_cache(new_tok, new_ref or refresh)
            return new_tok, None
        return None, "Granola API token is expired and refresh failed — open Granola to re-authenticate"

    return None, "Could not load Granola API token — open Granola to authenticate"


# --- API ---

def call_api(endpoint, payload, token):
    if not token:
        return None
    req = urllib.request.Request(
        f"{API_BASE}/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
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
        print(f"  [warn] API {endpoint} failed: {e}")
        return None


# --- Formatting helpers ---

class _HTMLToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
        self._current = []
        self._list_depth = 0

    def _flush(self):
        text = "".join(self._current).strip()
        self._current = []
        return text

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush()
        elif tag == "li":
            self._current = []
        elif tag == "ul":
            self._list_depth += 1
        elif tag == "p":
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4"):
            text = self._flush()
            if text:
                self.lines.append(f"{'#' * int(tag[1])} {text}")
        elif tag == "li":
            text = self._flush()
            if text:
                self.lines.append("  " * (self._list_depth - 1) + f"- {text}")
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
        text = "".join(prosemirror_to_markdown(c) for c in children)
        return f"{'#' * level} {text}"
    elif node_type == "paragraph":
        text = "".join(prosemirror_to_markdown(c) for c in children)
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
    return any(has_text_content(c) for c in (node.get("content") or []))


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
        ts = seg.get("start_timestamp", "")
        time_label = ""
        if ts:
            dt = parse_date(ts)
            if dt:
                time_label = dt.strftime("%H:%M:%S") + " "
        speaker = seg.get("detected_speaker_name") or (
            "System" if seg.get("source") == "system" else "Microphone"
        )
        lines.append(f"**[{time_label}{speaker}]** {text}")
    return "\n\n".join(lines) if lines else "_No transcript available._"


# --- Main ---

def main():
    today = datetime.now(timezone.utc).date()
    cutoff_date = today - timedelta(days=LOOKBACK_DAYS)
    warnings = []

    token, token_error = load_api_token()
    if token_error:
        print(f"  [warn] {token_error}")
        warnings.append(token_error)
    if not token:
        for w in warnings:
            slack_alert(f":warning: *Granola sync warning:* {w}")
        return

    docs = call_api("get-documents", {}, token)
    if not docs:
        msg = "get-documents API call failed — no meetings archived"
        print(f"  [error] {msg}")
        slack_alert(f":x: *Granola sync error:* {msg}")
        return

    synced = 0
    empty_notes = []

    for doc in docs:
        if doc.get("deleted_at") or doc.get("is_scratchpad"):
            continue

        title = doc.get("title")
        if not title:
            continue

        doc_date = parse_date(doc.get("created_at") or doc.get("updated_at"))
        if not doc_date or doc_date.date() < cutoff_date:
            continue

        doc_id = doc["id"]
        folder_name = doc_date.strftime("%Y-%m-%d")
        slug = slugify(title)
        folder = ARCHIVE_DIR / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        # --- Notes: try inline fields, then panels API ---
        ai_notes = ""

        notes_md = (doc.get("notes_markdown") or "").strip()
        if notes_md:
            ai_notes = notes_md
        else:
            notes_doc = doc.get("notes")
            if notes_doc and has_text_content(notes_doc):
                ai_notes = prosemirror_to_markdown(notes_doc)

        if not ai_notes:
            panels = call_api("get-document-panels", {"document_id": doc_id}, token)
            if panels and isinstance(panels, list):
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

        raw_notes = (doc.get("notes_plain") or "").strip()
        if not ai_notes and not raw_notes:
            empty_notes.append(f"{folder_name}/{title}")

        notes_content = f"# {title}\n\n**Date:** {doc_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        if ai_notes:
            notes_content += ai_notes + "\n"
        if raw_notes and raw_notes != ai_notes:
            notes_content += f"\n## My Notes\n\n{raw_notes}\n"
        if not ai_notes and not raw_notes:
            notes_content += "_No notes available._\n"

        (folder / f"{slug}-notes.md").write_text(notes_content, encoding="utf-8")

        # --- Transcript ---
        segments = call_api("get-document-transcript", {"document_id": doc_id}, token)
        transcript_content = (
            f"# {title} — Transcript\n\n"
            f"**Date:** {doc_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            + format_transcript(segments if isinstance(segments, list) else [])
        )
        (folder / f"{slug}-transcript.md").write_text(transcript_content, encoding="utf-8")

        print(f"  Saved: {folder_name}/{slug}")
        synced += 1

    print(f"\nDone. Synced {synced} meetings.")

    if empty_notes:
        msg = f":warning: *Granola sync:* {len(empty_notes)} meeting(s) archived with no notes:\n"
        msg += "\n".join(f"  • {m}" for m in empty_notes)
        print(f"\n[alert] {msg}")
        slack_alert(msg)

    if warnings:
        for w in warnings:
            print(f"\n[alert] :warning: *Granola sync warning:* {w}")
            slack_alert(f":warning: *Granola sync warning:* {w}")

    if synced == 0:
        msg = ":warning: *Granola sync:* ran but found 0 meetings to archive"
        print(f"\n[alert] {msg}")
        slack_alert(msg)


if __name__ == "__main__":
    main()
