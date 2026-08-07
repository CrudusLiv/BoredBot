"""Study Planner agent — builds a study schedule from deadlines and timetable."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

from datetime import datetime, timedelta, timezone

from agents import state as agent_state
from agents.deadline_tracker import run as get_deadlines
from core import llm

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
KL = timezone(timedelta(hours=8))

_SYSTEM = """\
You are a study planner for a CS university student in Kuala Lumpur.
Given their class timetable, upcoming deadlines, and today's date, produce a 7-day study plan.

Format:
**[Weekday DD Mon]**
- [Subject] — [Topic / task] — [Duration, e.g. 1 h]
- ...

Rules:
- Work around fixed lecture slots shown in the timetable
- Front-load work for items due within 5 days
- Include at least one review session per active subject per week
- Add a rest slot if the day already has 3+ study blocks
- Max 320 words total"""


def _load_schedule() -> str:
    path = VAULT / "SCHEDULE.md"
    try:
        return path.read_text(encoding="utf-8")[:3000]
    except (FileNotFoundError, OSError):
        return "(no schedule file found — treat all time slots as free)"


def run() -> str:
    today = datetime.now(tz=KL).strftime("%A, %d %b %Y")
    schedule = _load_schedule()
    deadlines = get_deadlines()
    prompt = (
        f"Today: {today}\n\n"
        f"Class timetable:\n{schedule}\n\n"
        f"Upcoming deadlines:\n{deadlines}\n\n"
        "Build the 7-day study plan."
    )
    result = llm.call(prompt, system_prompt=_SYSTEM, task="study_planner") or "Could not generate plan."
    agent_state.write_agent("study_planner", result.splitlines()[0] if result else "done")
    return result


if __name__ == "__main__":
    print(run())
