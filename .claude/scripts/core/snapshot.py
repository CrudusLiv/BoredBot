"""Snapshot: gather current state from all integrations + vault.
Diff: identify what's new since the last tick.

Snapshots are JSON-serialisable dicts; persisted at
.claude/data/state/heartbeat-state.json so each tick can compare against
the previous one. Each integration call is wrapped in _safe() so a single
failure (missing token, network blip) never crashes the tick."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
STATE_DIR = PROJECT_DIR / ".claude" / "data" / "state"
STATE_FILE = STATE_DIR / "heartbeat-state.json"

# Make the integrations package importable when this module is run from any cwd
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))


def _safe(fn) -> dict:
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def build_snapshot() -> dict:
    return {
        "timestamp": time.time(),
        "github":   _safe(_snapshot_github),
        "inbox":    _safe(_snapshot_inbox),
    }


def _snapshot_github() -> dict:
    from integrations import github_int
    rows = github_int.recent_pushes(days=1)
    clean = [r for r in rows if "error" not in r]
    return {"push_count": len(clean), "items": clean[:20]}


def _snapshot_inbox() -> dict:
    from integrations import vault_fs
    files = vault_fs.list_inbox_new()
    return {
        "count": len(files),
        "files": [str(f.relative_to(PROJECT_DIR)).replace("\\", "/") for f in files],
    }


# ---------- Diff ----------

def diff_snapshot(prev: dict | None, curr: dict) -> dict:
    prev = prev or {}
    return {
        "new_pushes":      _diff_by_id(prev.get("github", {}), curr.get("github", {}), "items", "sha"),
        "new_inbox_files": _diff_files(prev.get("inbox", {}),  curr.get("inbox", {})),
    }


def _diff_by_id(prev: dict, curr: dict, list_key: str, id_key: str) -> list:
    if not isinstance(curr, dict) or "error" in curr:
        return []
    prev_ids = {
        item.get(id_key) for item in (prev.get(list_key) or [])
        if isinstance(item, dict)
    }
    return [item for item in (curr.get(list_key) or []) if item.get(id_key) not in prev_ids]


def _diff_files(prev: dict, curr: dict) -> list:
    prev_set = set(prev.get("files") or [])
    return [f for f in (curr.get("files") or []) if f not in prev_set]


def has_changes(diff: dict) -> bool:
    return any([
        diff.get("new_pushes"),
        diff.get("new_inbox_files"),
    ])


# ---------- State persistence ----------

def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_state(snapshot: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)
