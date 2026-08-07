"""Tests for SCHEDULE.md → session context injection."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))


def reload_lib():
    """Reload _lib so module-level VAULT resolves to tmp_vault."""
    import _lib as m
    importlib.reload(m)
    return m


def _schedule(tmp_vault, day: str, lines: list[str]) -> None:
    content = "---\nsemester: 2026-S1\n---\n\n## Day Breakdown\n\n"
    content += f"### {day}\n"
    for line in lines:
        content += f"{line}\n"
    content += "\n### NextDay\n- 10:00 Placeholder\n"
    (tmp_vault / "SCHEDULE.md").write_text(content, encoding="utf-8")


def test_today_schedule_returns_todays_blocks(tmp_vault):
    today = datetime.now().strftime("%A")
    _schedule(tmp_vault, today, [
        "- 08:00–09:30 📚 CS101 (class)",
        "- 09:30–12:00 — free (2.5h)",
        "- 12:00–13:00 🏋️ Gym (recurring)",
    ])
    result = reload_lib().today_schedule()
    assert "08:00–09:30 📚 CS101" in result
    assert "09:30–12:00 — free" in result
    assert "12:00–13:00 🏋️ Gym" in result


def test_today_schedule_missing_file_returns_empty(tmp_vault):
    result = reload_lib().today_schedule()
    assert result == ""


def test_today_schedule_day_absent_from_file_returns_empty(tmp_vault):
    (tmp_vault / "SCHEDULE.md").write_text(
        "## Day Breakdown\n\n### SomeOtherDay\n- 08:00 Class\n",
        encoding="utf-8",
    )
    result = reload_lib().today_schedule()
    assert result == ""


def test_today_schedule_stops_at_next_section(tmp_vault):
    today = datetime.now().strftime("%A")
    _schedule(tmp_vault, today, ["- 08:00 CS101"])
    result = reload_lib().today_schedule()
    assert "08:00 CS101" in result        # positive: today's block is present
    assert "Placeholder" not in result    # negative: next section didn't bleed in


def test_build_session_context_includes_schedule(tmp_vault):
    today = datetime.now().strftime("%A")
    _schedule(tmp_vault, today, ["- 08:00–09:30 📚 CS101 (class)"])
    ctx = reload_lib().build_session_context()
    assert f"Today's Schedule ({today})" in ctx
    assert "CS101" in ctx


def test_build_session_context_omits_schedule_when_file_missing(tmp_vault):
    ctx = reload_lib().build_session_context()
    assert "Today's Schedule" not in ctx
