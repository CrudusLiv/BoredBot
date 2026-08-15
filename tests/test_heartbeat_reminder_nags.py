"""voice/heartbeat.py::_check_reminder_nags -- speak every due/overdue
Google Tasks reminder together on a fixed clock grid anchored at
briefing_time and repeating every reminder_nag_interval_minutes, until
each is marked done."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {
    "timezone_offset_hours": 8, "reminder_nag_enabled": True,
    "reminder_nag_interval_minutes": 120,
}

TZ8 = timezone(timedelta(hours=8))


def _env(tmp_path, monkeypatch, conf=None, hour=10, minute=0):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    fixed_now = datetime(2026, 7, 7, hour, minute, tzinfo=TZ8)
    monkeypatch.setattr(hb_mod, "datetime", type("F", (), {
        "now": staticmethod(lambda tz=None: fixed_now),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def _hb(tmp_path, monkeypatch, spoken):
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    monkeypatch.setattr(hb, "_speak", lambda text: spoken.append(text))
    return hb


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, reminder_nag_enabled=False))
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert spoken == []
    assert posts == []


def test_no_due_reminders_does_nothing(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert spoken == []
    assert posts == []
    assert hb._reminder_nag_slot is None


def test_nags_new_due_reminder_on_current_slot(tmp_path, monkeypatch):
    # 10:00 local, default briefing_time 09:00, 120-min grid -> current
    # slot is 09:00 (the 09:00-11:00 window).
    posts = _env(tmp_path, monkeypatch, hour=10, minute=0)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert len(spoken) == 1
    assert "Renew passport" in spoken[0]
    assert len(posts) == 1
    assert hb._reminder_nag_slot == datetime(2026, 7, 7, 9, 0, tzinfo=TZ8)


def test_does_not_renag_within_same_slot(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, hour=10, minute=45)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    # Already fired for today's 09:00 slot -- 10:45 is still inside it.
    hb._reminder_nag_slot = datetime(2026, 7, 7, 9, 0, tzinfo=TZ8)
    hb._check_reminder_nags()
    assert spoken == []
    assert posts == []


def test_renags_once_next_fixed_slot_starts(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, hour=11, minute=1)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    # Fired for the 09:00 slot; 11:01 has crossed into the next fixed
    # slot (11:00), so it re-nags even though only a minute has passed
    # since the grid boundary.
    hb._reminder_nag_slot = datetime(2026, 7, 7, 9, 0, tzinfo=TZ8)
    hb._check_reminder_nags()
    assert len(spoken) == 1
    assert hb._reminder_nag_slot == datetime(2026, 7, 7, 11, 0, tzinfo=TZ8)


def test_does_not_renag_just_before_next_slot(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, hour=10, minute=59)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._reminder_nag_slot = datetime(2026, 7, 7, 9, 0, tzinfo=TZ8)
    hb._check_reminder_nags()
    assert spoken == []
    assert posts == []


def test_multiple_reminders_nagged_together_on_same_slot(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
        {"id": "t2", "title": "Pay rent", "due": "y"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert len(spoken) == 2
    assert len(posts) == 2
    assert hb._reminder_nag_slot == datetime(2026, 7, 7, 9, 0, tzinfo=TZ8)


def test_grid_anchors_to_configured_briefing_time(tmp_path, monkeypatch):
    # briefing_time 07:30 -> slots at 07:30, 09:30, 11:30... At 11:45 the
    # current slot is 11:30, not the default-anchor's 11:00.
    posts = _env(tmp_path, monkeypatch, dict(CONF, briefing_time="07:30"), hour=11, minute=45)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert len(spoken) == 1
    assert hb._reminder_nag_slot == datetime(2026, 7, 7, 11, 30, tzinfo=TZ8)
