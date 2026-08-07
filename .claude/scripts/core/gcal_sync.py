"""Heartbeat task: push DEADLINES.md rows and `gcal:` tags to Google Calendar.

State file (.claude/data/gcal_synced.json) maps "<title>::<date>" → event_id
so we don't re-query GCal on every tick. The dedup inside create_event is
still the source of truth — this file is just a fast-path cache.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
from integrations import gcal_write  # noqa: E402

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
STATE_PATH = PROJECT_DIR / ".claude" / "data" / "gcal_synced.json"


def _load_state() -> dict[str, str]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _key(title: str, date: str) -> str:
    return f"{title.strip().lower()}::{date}"


def sync_deadlines() -> int:
    """Push every new DEADLINES.md row. Returns count of newly created events."""
    deadlines_md = VAULT / "DEADLINES.md"
    if not deadlines_md.exists():
        return 0
    rows = gcal_write.parse_deadlines_md(deadlines_md.read_text(encoding="utf-8"))
    state = _load_state()
    created = 0
    for date, title in rows:
        k = _key(title, date)
        if k in state:
            continue
        try:
            event_id = gcal_write.create_event(title, date, description="from DEADLINES.md")
        except Exception as exc:
            print(f"gcal_sync: create_event failed for {title}@{date}: {exc}", file=sys.stderr)
            continue
        if event_id:
            state[k] = event_id
            created += 1
        else:
            # Already on calendar — record as synced so we don't ping GCal again.
            state[k] = "duplicate"
    _save_state(state)
    return created


def _replace_tag_line(text: str, original_line: str, event_id: str) -> str:
    """Replace `gcal: <date> | <title>` with `... [synced:<id>]`."""
    new_line = original_line.rstrip() + f" [synced:{event_id}]"
    return text.replace(original_line, new_line, 1)


def sync_tags_in_file(path: Path) -> int:
    """Push every `gcal:` tag in `path`, rewrite each successful line with
    `[synced:<id>]`. Returns count of newly created events."""
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    created = 0
    changed = False
    for line in text.splitlines():
        if "[synced:" in line:
            continue
        m = re.search(r"gcal:\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+)$", line)
        if not m:
            continue
        date, title = m.group(1), m.group(2).strip()
        try:
            event_id = gcal_write.create_event(title, date, description=f"from {path.name}")
        except Exception as exc:
            print(f"gcal_sync: create_event failed for tag in {path.name}: {exc}", file=sys.stderr)
            continue
        if event_id:
            created += 1
            text = _replace_tag_line(text, line, event_id)
            changed = True
        else:
            text = _replace_tag_line(text, line, "duplicate")
            changed = True
    if changed:
        path.write_text(text, encoding="utf-8")
    return created


def sync_tags_in_daily_and_memory() -> int:
    """Scan daily/YYYY-MM-DD.md (today + yesterday) and MEMORY.md for tags."""
    from datetime import datetime, timedelta, timezone
    KL = timezone(timedelta(hours=8))
    today = datetime.now(KL).date()
    candidates = [
        VAULT / "MEMORY.md",
        VAULT / "daily" / f"{today.isoformat()}.md",
        VAULT / "daily" / f"{(today - timedelta(days=1)).isoformat()}.md",
    ]
    total = 0
    for p in candidates:
        total += sync_tags_in_file(p)
    return total


def run() -> int:
    """Heartbeat entry point: combined DEADLINES + tag sync. Returns total
    new events created."""
    return sync_deadlines() + sync_tags_in_daily_and_memory()
