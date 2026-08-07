"""Progress Monitor agent — weekly habit and study progress summary."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

from agents import state as agent_state
from core import llm

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
KL = timezone(timedelta(hours=8))

_SYSTEM = """\
You are a weekly progress analyst for a CS student. Given their habit log and recent \
daily notes, write a concise summary structured as:

**Habits this week**
- Classes attended: X / Y days (or "no schedule data")
- Sleep: checked X / Y days
- Budget: tracked X / Y days
- Overall: X% completion

**Study activity**
2–3 bullets on what was actually worked on, drawn from the daily logs. Be specific \
(e.g. "Reviewed linked lists Wed + Thu", not just "studied CS").

**Streak & momentum**
One sentence on current streak and trajectory.

**One note**
A single honest observation — not generic motivation. If numbers are bad, say so plainly.

Max 180 words. Use only what the data actually shows — no invented details."""


def _load_habits() -> str:
    path = VAULT / "HABITS.md"
    try:
        return path.read_text(encoding="utf-8")[:2000]
    except (FileNotFoundError, OSError):
        return "(no HABITS.md found)"


def _load_recent_dailies(n: int = 7) -> str:
    daily_dir = VAULT / "daily"
    today = datetime.now(tz=KL).date()
    texts: list[str] = []
    for i in range(n):
        d = today - timedelta(days=i)
        path = daily_dir / f"{d}.md"
        try:
            texts.append(f"--- {d} ---\n{path.read_text(encoding='utf-8')[:800]}")
        except (FileNotFoundError, OSError):
            continue
    return "\n\n".join(texts) or "(no daily logs found)"


def run() -> str:
    today = datetime.now(tz=KL).strftime("%A, %d %b %Y")
    habits = _load_habits()
    dailies = _load_recent_dailies()
    prompt = (
        f"Today: {today}\n\n"
        f"HABITS.md:\n{habits}\n\n"
        f"Last 7 daily logs:\n{dailies}"
    )
    result = llm.call(prompt, system_prompt=_SYSTEM, task="progress_monitor") or "Could not generate summary."
    agent_state.write_agent("progress_monitor", result.splitlines()[0] if result else "done")
    return result


if __name__ == "__main__":
    print(run())
