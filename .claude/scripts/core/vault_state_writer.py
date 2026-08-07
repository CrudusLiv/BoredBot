"""Write heartbeat snapshots to vault-readable files in Dynamous/Memory/state/.

Dataview can only read files inside the Obsidian vault. This module bridges
the gap between .claude/data/state/ and the vault on each heartbeat tick."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _vault_state_dir() -> Path:
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return base / "Dynamous" / "Memory" / "state"


def _iso(ts: float | None = None) -> str:
    if ts is None:
        ts = time.time()
    t = datetime.fromtimestamp(ts, tz=timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def write_github(snapshot: dict) -> None:
    github = snapshot.get("github") or {}
    if "error" in github:
        return

    push_count = github.get("push_count", 0)
    content = (
        f"---\n"
        f"updated: {_iso(snapshot.get('timestamp'))}\n"
        f"prs_open: {push_count}\n"
        f"notifications: 0\n"
        f"---\n"
    )

    d = _vault_state_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "github-counts.md").write_text(content, encoding="utf-8")


def write_heartbeat_state(snapshot: dict) -> None:
    d = _vault_state_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "heartbeat-state.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_gcal_today(snapshot: dict) -> None:
    gcal = snapshot.get("gcal") or {}
    if "error" in gcal or not gcal.get("events"):
        return

    kl = timezone(timedelta(hours=8))
    today = datetime.now(tz=kl).date()

    events = []
    for e in gcal.get("events", []):
        try:
            start_dt = datetime.fromisoformat(e.get("start", ""))
        except ValueError:
            continue
        if start_dt.astimezone(kl).date() != today:
            continue
        events.append((start_dt.strftime("%H:%M"), e.get("summary", "(no title)")))

    if not events:
        return

    events.sort()
    lines = ["---", f"updated: {_iso(snapshot.get('timestamp'))}", f"date: {today}", "---", ""]
    for time_str, summary in events:
        lines.append(f"- {time_str}: {summary}")

    d = _vault_state_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "gcal-today.md").write_text("\n".join(lines), encoding="utf-8")


def write_all(snapshot: dict) -> None:
    write_github(snapshot)
    write_gcal_today(snapshot)
    write_heartbeat_state(snapshot)
