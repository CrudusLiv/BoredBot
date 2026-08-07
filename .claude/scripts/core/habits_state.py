"""JSON-backed state store for habit streak and history tracking.

State file: .claude/data/state/habits_state.json

Schema:
{
    "current_streak": 3,
    "best_streak": 5,
    "history": {
        "2026-06-10": {"Lecture engagement": true, "Project progress": true},
        "2026-06-11": {"Research / learning": true}
    }
}
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
STATE_FILE = PROJECT_DIR / ".claude" / "data" / "state" / "habits_state.json"
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def load_state() -> dict:
    """Return state dict, or empty defaults if file missing/corrupt."""
    if not STATE_FILE.exists():
        return {"current_streak": 0, "best_streak": 0, "history": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        data.setdefault("current_streak", 0)
        data.setdefault("best_streak", 0)
        data.setdefault("history", {})
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return {"current_streak": 0, "best_streak": 0, "history": {}}


def save_state(state: dict) -> None:
    """Atomic write via .tmp -> rename."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def compute_streak(history: dict, as_of: str) -> int:
    """Count consecutive days ending at as_of where >=1 pillar was completed.

    Clamps as_of to today so future-dated history entries never inflate the streak."""
    try:
        current = date.fromisoformat(as_of)
    except ValueError:
        return 0
    current = min(current, date.today())

    streak = 0
    day = current
    while True:
        day_str = day.isoformat()
        day_history = history.get(day_str, {})
        if any(v for v in day_history.values()):
            streak += 1
            day -= timedelta(days=1)
        else:
            break
    return streak


def record_completion(day: str, pillar: str) -> dict:
    """Mark pillar done for YYYY-MM-DD date. Recomputes streak. Returns updated state.

    Raises ValueError for malformed date strings."""
    try:
        day = date.fromisoformat(day).isoformat()
    except ValueError:
        raise ValueError(f"record_completion: invalid date {day!r}")

    state = load_state()
    history = state["history"]

    if day not in history:
        history[day] = {}
    history[day][pillar] = True

    # Recompute current streak as of the latest recorded day
    all_days = sorted(history.keys())
    latest_day = all_days[-1] if all_days else day
    current = compute_streak(history, latest_day)

    state["current_streak"] = current
    if current > state.get("best_streak", 0):
        state["best_streak"] = current

    save_state(state)
    return state


def get_weekly_summary(history: dict, week_start: str, total: int = 0) -> list[dict]:
    """Return 7 dicts for days starting from week_start.

    Each dict: {date, weekday, completions, total, pct}
    total should be the current number of tracked pillars.
    """
    try:
        start = date.fromisoformat(week_start)
    except ValueError:
        return []

    result = []
    for i in range(7):
        day = start + timedelta(days=i)
        day_str = day.isoformat()
        day_history = history.get(day_str, {})
        completions = sum(1 for v in day_history.values() if v)
        pct = round(completions / total * 100) if total > 0 else 0
        result.append({
            "date": day_str,
            "weekday": _WEEKDAYS[day.weekday()],
            "completions": completions,
            "total": total,
            "pct": pct,
        })
    return result
