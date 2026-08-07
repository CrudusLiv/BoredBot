"""Append-only JSONL log of every vault action.

Every action emits one entry. `undo` reads the last entry, executes the
inverse, and appends the inverse as a new entry — so undo-undo works.

The log is never auto-pruned. Disk cost is negligible (a few KB / day).

The log path is resolved at call time (not module-import time) so that
tests which monkeypatch CLAUDE_PROJECT_DIR actually redirect the writes.
An earlier baked-in LOG_PATH constant let test runs leak entries into
the real log, which then drove a real `undo` to truncate a real file."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

KL = timezone(timedelta(hours=8))


def _log_path() -> Path:
    """Resolve the transaction log path right now, reading CLAUDE_PROJECT_DIR
    each call. Tests monkeypatching the env var get redirected automatically."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return project_dir / ".claude" / "data" / "vault_transactions.jsonl"


def append(entry: dict) -> None:
    """Append one entry to the JSONL log. Auto-stamps `ts` if missing."""
    if "ts" not in entry:
        entry = {**entry, "ts": datetime.now(KL).isoformat()}
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_last() -> Optional[dict]:
    """Return the most recent entry, or None if the log is empty/missing."""
    log = _log_path()
    if not log.exists():
        return None
    last_line = ""
    with log.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line:
                last_line = line
    if not last_line:
        return None
    try:
        return json.loads(last_line)
    except json.JSONDecodeError:
        return None
