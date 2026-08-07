"""Deadline Tracker agent — scans vault for upcoming deadlines."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

from agents import state as agent_state
from core import llm

VAULT = PROJECT_DIR / "Dynamous" / "Memory"

_DEADLINE_RE = re.compile(
    r"(?:due|deadline|submit|submission|hand.?in|assignment|lab|project|report|"
    r"presentation|midterm|final|exam|quiz|test|complete.?by|due.?date|hw\b)\b.*",
    re.IGNORECASE,
)

_SYSTEM = """\
You are a deadline extraction assistant for a CS student in Kuala Lumpur (UTC+8).
Given lines from study notes (with source file names), extract all upcoming deadlines.

Output format — a bullet list sorted by date, one item per line:
  • [Course] · [Item] · [Date/timeframe] · [Source file]

Rules:
- Only include items with a recognisable date or explicit timeframe ("this Friday", "Week 3", etc.)
- Omit vague lines with no time reference
- If nothing qualifies, reply exactly: No deadlines found.
- Do not add commentary outside the list"""


def _gather_lines(vault: Path) -> list[str]:
    hits: list[str] = []
    for f in vault.rglob("*.md"):
        # skip daily logs — deadlines live in course notes, not journals
        if "daily" in f.parts:
            continue
        try:
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                if _DEADLINE_RE.search(line):
                    hits.append(f"[{f.stem}] {line.strip()}")
        except OSError:
            continue
    return hits[:300]


def run() -> str:
    lines = _gather_lines(VAULT)
    if not lines:
        result = "No deadlines found in vault."
        agent_state.write_agent("deadline_tracker", result)
        return result

    prompt = "Lines from my study notes that may contain deadlines:\n\n" + "\n".join(f"- {l}" for l in lines)
    result = llm.call(prompt, system_prompt=_SYSTEM, task="deadline_tracker") or "No deadlines found."
    agent_state.write_agent("deadline_tracker", result.splitlines()[0] if result else "done")
    return result


if __name__ == "__main__":
    print(run())
