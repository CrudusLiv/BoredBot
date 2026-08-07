"""voice/heartbeat.py::_check_git_todo_summary — once-daily commit/todo digest."""
from __future__ import annotations

from datetime import date

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {
    "timezone_offset_hours": 8, "git_todo_summary_enabled": True,
    "git_todo_summary_time": "20:00", "vault_path": "",
}


def _env(tmp_path, monkeypatch, conf=None, hour=20, minute=5):
    from datetime import datetime, timezone, timedelta
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    fixed_now = datetime(2026, 7, 7, hour, minute, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(hb_mod, "datetime", type(
        "F", (), {"now": staticmethod(lambda tz=None: fixed_now)}
    ))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_summary_when_due(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.git_digest, "recent_commits", lambda repo, since_hours=24: [
        {"sha": "abc1234", "date": "2026-07-07T10:00:00+08:00", "message": "fix bug"},
    ])
    monkeypatch.setattr(hb_mod.todo_tracker, "unchecked_todos", lambda vault: ["Ship plan"])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_git_todo_summary()
    assert len(posts) == 1
    assert "1 commit" in posts[0]
    assert "1 todo" in posts[0] or "Ship plan" in posts[0]


def test_before_scheduled_time_does_nothing(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, hour=19, minute=0)
    monkeypatch.setattr(hb_mod.git_digest, "recent_commits", lambda repo, since_hours=24: [])
    monkeypatch.setattr(hb_mod.todo_tracker, "unchecked_todos", lambda vault: [])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_git_todo_summary()
    assert posts == []


def test_only_fires_once_per_day(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.git_digest, "recent_commits", lambda repo, since_hours=24: [
        {"sha": "abc1234", "date": "x", "message": "fix bug"}
    ])
    monkeypatch.setattr(hb_mod.todo_tracker, "unchecked_todos", lambda vault: [])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._git_todo_done_date = date(2026, 7, 7)
    hb._check_git_todo_summary()
    assert posts == []


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, git_todo_summary_enabled=False))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_git_todo_summary()
    assert posts == []
