#!/usr/bin/env python3
"""Manual refresh -- gather a snapshot from integrations and write vault state files.

No LLM calls, no notifications. Just data gather + vault write.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
VAULT = PROJECT_DIR / "Dynamous" / "Memory"

sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts" / "integrations"))

import _env  # noqa: F401, E402

from core import snapshot, vault_state_writer  # noqa: E402
from finance import tracker as finance_tracker  # noqa: E402

KL = timezone(timedelta(hours=8))


def _write_log(lines: list[str]) -> None:
    dt = datetime.now(tz=KL).strftime("%Y-%m-%dT%H:%M:%S")
    content = f"---\nupdated: {dt}\n---\n" + "\n".join(lines) + "\n"
    state_dir = VAULT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "refresh-log.md").write_text(content, encoding="utf-8")


def main() -> int:
    lines: list[str] = []
    dt = datetime.now(tz=KL).strftime("%H:%M · %Y-%m-%d")
    lines.append(f"Last refresh: {dt}")

    prev_saved = snapshot.load_state()
    # Skip the GitHub API call: it dominates the refresh latency (~19s vs
    # ~150ms for everything else) and the scheduled 30-min heartbeat already
    # keeps github-counts.md fresh. Carry forward the last heartbeat's github
    # snapshot so write_github() has data instead of blanking the file.
    curr = {
        "timestamp": time.time(),
        "github":  (prev_saved or {}).get("github") or {},
    }
    # Preserve the scheduled heartbeat run time so the dashboard "Last ran"
    # shows when the heartbeat actually fired, not when the user hit Refresh.
    if prev_saved and prev_saved.get("heartbeat_ran_at"):
        curr["heartbeat_ran_at"] = prev_saved["heartbeat_ran_at"]
    vault_state_writer.write_all(curr)
    snapshot.save_state(curr)
    # Re-derive this month's finance Summary/Timeline from whatever's in the
    # Entries table -- picks up rows typed by hand in Obsidian, not just
    # voice-logged ones. No-op if the current month has no file yet.
    finance_tracker.recalc_month()

    github = curr.get("github") or {}

    github_detail = "(unavailable — carried from last heartbeat)" if github.get("error") else f"{github.get('push_count', 0)} pushes"
    lines.append(f"  GitHub:  {github_detail}")
    lines.append("Done.")

    _write_log(lines)
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
