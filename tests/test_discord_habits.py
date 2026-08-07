"""Tests for habits slash-command helpers in discord_bot."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude"))


_TEST_PILLARS = ["Lecture engagement", "Project progress", "Research / learning", "Personal goals"]


def test_run_habits_check_fuzzy_match(monkeypatch):
    """Partial pillar name matches correctly."""
    import integrations._env  # noqa: F401
    mock_check = MagicMock(return_value=True)
    with patch.dict(sys.modules, {}):
        import chat.discord_bot as bot
        monkeypatch.setattr(bot.habits, "get_pillar_names", lambda: _TEST_PILLARS)
        monkeypatch.setattr(bot.habits, "check_pillar", mock_check)
        reaction, msg = bot.run_habits_check("research")
    assert reaction == "✅"
    assert "Research / learning" in msg
    mock_check.assert_called_once_with("Research / learning")


def test_run_habits_check_unknown(monkeypatch):
    """Unknown pillar returns ❓."""
    import integrations._env  # noqa: F401
    import chat.discord_bot as bot
    reaction, msg = bot.run_habits_check("meditation")
    assert reaction == "❓"
    assert "Choose from" in msg


def test_run_habits_check_already_done(monkeypatch):
    """Returns ✅ with 'Already done' when pillar was already checked."""
    import integrations._env  # noqa: F401
    import chat.discord_bot as bot
    monkeypatch.setattr(bot.habits, "get_pillar_names", lambda: _TEST_PILLARS)
    monkeypatch.setattr(bot.habits, "check_pillar", MagicMock(return_value=False))
    reaction, msg = bot.run_habits_check("lecture")
    assert reaction == "✅"
    assert "Already done" in msg


def test_run_habits_status_returns_embed(monkeypatch):
    """Returns no error and an embed object with correct title."""
    import integrations._env  # noqa: F401
    import discord
    import chat.discord_bot as bot

    fake_data = {
        "today": "2026-06-13",
        "categories": {"Academic": ["Lecture engagement"]},
        "category_emoji": {"Academic": "🎓"},
        "checked": {"Lecture engagement": True},
        "done_count": 1,
        "total": 4,
        "current_streak": 3,
        "best_streak": 5,
        "weekly": [
            {"weekday": "Monday", "pct": 100, "completions": 4, "total": 4, "date": "2026-06-09"},
            {"weekday": "Tuesday", "pct": 50, "completions": 2, "total": 4, "date": "2026-06-10"},
            {"weekday": "Wednesday", "pct": 0, "completions": 0, "total": 4, "date": "2026-06-11"},
            {"weekday": "Thursday", "pct": 0, "completions": 0, "total": 4, "date": "2026-06-12"},
            {"weekday": "Friday", "pct": 100, "completions": 4, "total": 4, "date": "2026-06-13"},
            {"weekday": "Saturday", "pct": 0, "completions": 0, "total": 4, "date": "2026-06-14"},
            {"weekday": "Sunday", "pct": 0, "completions": 0, "total": 4, "date": "2026-06-15"},
        ],
    }
    monkeypatch.setattr(bot.habits, "get_status_data", MagicMock(return_value=fake_data))

    err, emb = bot.run_habits_status()
    assert err is None
    assert isinstance(emb, discord.Embed)
    assert "Sat 13 Jun 2026" in emb.title
