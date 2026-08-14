"""voice/heartbeat.py::_evening_wrap / _morning_briefing — Google Tasks
reminders must surface in both check-ins, not just calendar events +
DEADLINES.md (they live on a separate Tasks list; see _fetch_reminders)."""
from __future__ import annotations

import queue
from datetime import datetime, timedelta, timezone

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _env(tmp_path, monkeypatch, conf, events=None, reminders=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf))
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: None)  # no DEADLINES.md
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    monkeypatch.setattr(hb_mod, "_fetch_events", lambda *a, **k: events or [])
    monkeypatch.setattr(hb_mod, "_fetch_reminders", lambda *a, **k: reminders or [])
    return posts


def _speaking_heartbeat():
    q: "queue.Queue[str]" = queue.Queue()
    hb = Heartbeat(interval_minutes=30, speak_queue=q, proactive_tts=True, idle_fn=lambda: None)
    return hb, q


def _conf(now, **overrides):
    # wrap_time / briefing_time a couple minutes in the past so the
    # once-a-day guards let the check-in fire, without tripping the
    # morning briefing's >1h "catch-up" branch.
    trigger = _hhmm(now - timedelta(minutes=2))
    base = {
        "timezone_offset_hours": 0,
        "briefing_enabled": True,
        "wrap_time": trigger,
        "briefing_time": trigger,
    }
    base.update(overrides)
    return base


def test_evening_wrap_mentions_reminder_when_no_calendar_event(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    reminders = [{"id": "1", "title": "Renew passport", "due": f"{tomorrow}T00:00:00.000Z", "notes": ""}]
    _env(tmp_path, monkeypatch, _conf(now), reminders=reminders)
    hb, q = _speaking_heartbeat()
    hb._evening_wrap()
    text = q.get_nowait()
    assert "Renew passport" in text
    assert "Nothing scheduled for tomorrow" not in text


def test_evening_wrap_says_nothing_scheduled_when_truly_empty(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _env(tmp_path, monkeypatch, _conf(now))
    hb, q = _speaking_heartbeat()
    hb._evening_wrap()
    text = q.get_nowait()
    assert "Nothing scheduled for tomorrow" in text


def test_evening_wrap_mentions_both_event_and_reminder(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    events = [{"summary": "Dentist", "start": f"{tomorrow}T09:00:00"}]
    reminders = [{"id": "1", "title": "Renew passport", "due": f"{tomorrow}T00:00:00.000Z", "notes": ""}]
    _env(tmp_path, monkeypatch, _conf(now), events=events, reminders=reminders)
    hb, q = _speaking_heartbeat()
    hb._evening_wrap()
    text = q.get_nowait()
    assert "Dentist" in text
    assert "Renew passport" in text


def test_morning_briefing_includes_tomorrow_reminder(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    reminders = [{"id": "1", "title": "Renew passport", "due": f"{tomorrow}T00:00:00.000Z", "notes": ""}]
    _env(tmp_path, monkeypatch, _conf(now), reminders=reminders)
    hb, q = _speaking_heartbeat()
    hb._morning_briefing()
    text = q.get_nowait()
    assert "Renew passport" in text


def test_morning_briefing_includes_today_reminder(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    reminders = [{"id": "1", "title": "Pay rent", "due": f"{today}T00:00:00.000Z", "notes": ""}]
    _env(tmp_path, monkeypatch, _conf(now), reminders=reminders)
    hb, q = _speaking_heartbeat()
    hb._morning_briefing()
    text = q.get_nowait()
    assert "Pay rent" in text
