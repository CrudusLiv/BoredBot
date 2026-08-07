"""Tests for habits.auto_check daily-log wiring."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

from core import habits
import core.habits_state as hs
import vault.daily as daily_mod

HABITS_TEMPLATE = (
    "- [ ] **Lecture engagement**\n"
    "- [ ] **Project progress**\n"
    "- [ ] **Research / learning**\n"
    "- [ ] **Personal goals**\n"
)


@pytest.fixture(autouse=True)
def _patch_habits_paths(tmp_vault, monkeypatch):
    """Redirect module-level path constants so tests never touch the real vault."""
    monkeypatch.setattr(habits, "HABITS", tmp_vault / "HABITS.md")
    monkeypatch.setattr(habits, "LECTURES", tmp_vault / "lectures")
    monkeypatch.setattr(habits, "_load_config", lambda: {
        "auto_detect": {"Lecture engagement": "lectures_touched_today"},
        "categories": {},
        "category_emoji": {},
    })


def test_auto_check_writes_habit_line_for_newly_ticked(tmp_vault, monkeypatch):
    (tmp_vault / "HABITS.md").write_text(HABITS_TEMPLATE, encoding="utf-8")
    (tmp_vault / "lectures" / "CS101").mkdir(parents=True, exist_ok=True)
    (tmp_vault / "lectures" / "CS101" / "note.md").write_text("x", encoding="utf-8")

    written: list[str] = []
    monkeypatch.setattr(daily_mod, "append_line", lambda line: written.append(line))

    newly = habits.auto_check({})
    assert "Lecture engagement" in newly
    assert "Habit: Lecture engagement" in written


def test_auto_check_no_write_when_nothing_ticked(tmp_vault, monkeypatch):
    (tmp_vault / "HABITS.md").write_text(HABITS_TEMPLATE, encoding="utf-8")

    written: list[str] = []
    monkeypatch.setattr(daily_mod, "append_line", lambda line: written.append(line))

    newly = habits.auto_check({})
    assert newly == []
    assert written == []


def test_auto_check_no_write_when_already_checked(tmp_vault, monkeypatch):
    already = HABITS_TEMPLATE.replace(
        "- [ ] **Lecture engagement**", "- [x] **Lecture engagement**"
    )
    (tmp_vault / "HABITS.md").write_text(already, encoding="utf-8")
    (tmp_vault / "lectures" / "CS101").mkdir(parents=True, exist_ok=True)
    (tmp_vault / "lectures" / "CS101" / "note.md").write_text("x", encoding="utf-8")

    written: list[str] = []
    monkeypatch.setattr(daily_mod, "append_line", lambda line: written.append(line))

    newly = habits.auto_check({})
    assert newly == []
    assert written == []


def test_check_pillar_newly_checked(tmp_vault, monkeypatch):
    (tmp_vault / "HABITS.md").write_text(HABITS_TEMPLATE, encoding="utf-8")

    monkeypatch.setattr(hs, "record_completion", lambda day, pillar: None)
    monkeypatch.setattr(daily_mod, "append_line", lambda line: None)

    result = habits.check_pillar("Research / learning")
    assert result is True
    content = (tmp_vault / "HABITS.md").read_text(encoding="utf-8")
    assert "- [x] **Research / learning**" in content


def test_check_pillar_already_done(tmp_vault, monkeypatch):
    already = HABITS_TEMPLATE.replace(
        "- [ ] **Personal goals**", "- [x] **Personal goals**"
    )
    (tmp_vault / "HABITS.md").write_text(already, encoding="utf-8")

    result = habits.check_pillar("Personal goals")
    assert result is False


def test_check_pillar_unknown(tmp_vault):
    result = habits.check_pillar("Meditation")
    assert result is False


def test_get_status_data_keys(tmp_vault, monkeypatch):
    (tmp_vault / "HABITS.md").write_text(HABITS_TEMPLATE, encoding="utf-8")

    monkeypatch.setattr(hs, "load_state", lambda: {"current_streak": 2, "best_streak": 3, "history": {}})
    monkeypatch.setattr(hs, "get_weekly_summary", lambda history, week_start, total=0: [])

    data = habits.get_status_data()
    for key in ("today", "categories", "category_emoji", "checked", "done_count", "total", "current_streak", "best_streak", "weekly"):
        assert key in data, f"missing key: {key}"
    assert data["current_streak"] == 2
