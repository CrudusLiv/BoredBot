"""Idempotency state for the heartbeat dashboard layer.

Sidecar JSON at .claude/data/dashboard_state.json. Each top-level
key is a namespace owned by one slice:

  heartbeat   -- Slice 1 (heartbeat throttle bookkeeping)
  deadlines   -- Slice 3 (per-row threshold tracking)
  lectures    -- Slice 4 (per-note identifiers)
  pr_activity -- Slice 5 (per-PR last-event-id)

Each slice should only read/write its own namespace. load() seeds missing
keys from DEFAULT_STATE so forward-compatible adds don't break old state
files."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
STATE_FILE = PROJECT_DIR / ".claude" / "data" / "dashboard_state.json"

DEFAULT_STATE: dict[str, Any] = {
    "heartbeat": {"last_status": None, "last_tick_ts": 0},
    "deadlines": {},
    "lectures": {},
    "pr_activity": {},
    "next3": {"thread_id": None, "message_id": None},
}


def load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return copy.deepcopy(DEFAULT_STATE)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(DEFAULT_STATE)
    if not isinstance(state, dict):
        return copy.deepcopy(DEFAULT_STATE)
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, copy.deepcopy(v))
    return state


def save(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)
