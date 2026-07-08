"""voice/heartbeat.py::_check_spaced_repetition — daily due-cards reminder."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "spaced_repetition_enabled": True, "review_reminder_time": "10:00"}


def _env(tmp_path, monkeypatch, conf=None, hour=10, minute=5):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    fixed_now = datetime(2026, 7, 7, hour, minute, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(hb_mod, "datetime", type("F", (), {"now": staticmethod(lambda tz=None: fixed_now)}))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_reminder_when_cards_due(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.spaced_repetition, "due_cards", lambda: [{"id": "1"}, {"id": "2"}])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_spaced_repetition()
    assert len(posts) == 1
    assert "2" in posts[0]


def test_no_notice_when_nothing_due(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.spaced_repetition, "due_cards", lambda: [])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_spaced_repetition()
    assert posts == []


def test_only_fires_once_per_day(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.spaced_repetition, "due_cards", lambda: [{"id": "1"}])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._review_reminder_done_date = date(2026, 7, 7)
    hb._check_spaced_repetition()
    assert posts == []


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, spaced_repetition_enabled=False))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_spaced_repetition()
    assert posts == []
