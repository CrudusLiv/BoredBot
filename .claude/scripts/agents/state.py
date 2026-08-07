"""Agent mission-control state — read/write agent_state.json."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agents.registry import AGENTS

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
STATE_FILE = PROJECT_DIR / ".claude" / "data" / "agent_state.json"

_DEFAULT_ENTRY: dict = {"last_run": None, "last_result": "Never run", "status": "idle"}


def read_state() -> dict[str, dict]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}
    return {name: raw.get(name, dict(_DEFAULT_ENTRY)) for name in AGENTS}


def write_agent(name: str, result: str, status: str = "ok") -> None:
    state = read_state()
    state[name] = {
        "last_run": datetime.now(tz=timezone.utc).isoformat(),
        "last_result": result[:200],
        "status": status,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
