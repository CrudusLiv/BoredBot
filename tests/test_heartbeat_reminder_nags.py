"""voice/heartbeat.py::_check_reminder_nags — repeat a spoken reminder
every reminder_nag_interval_minutes for each due/overdue Google Tasks
reminder until it's marked done."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {
    "timezone_offset_hours": 8, "reminder_nag_enabled": True,
    "reminder_nag_interval_minutes": 120,
}


def _env(tmp_path, monkeypatch, conf=None, hour=10, minute=0):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    fixed_now = datetime(2026, 7, 7, hour, minute, tzinfo=timezone(timedelta(hours=8)))
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


def test_nags_new_due_reminder(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert len(spoken) == 1
    assert "Renew passport" in spoken[0]
    assert len(posts) == 1
    assert "t1" in hb._reminder_nag_last


def test_does_not_renag_within_interval(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    # now (10:00 +08:00) is 02:00 UTC; nagged 30 minutes ago -- well under
    # the 120-minute interval.
    hb._reminder_nag_last["t1"] = datetime(2026, 7, 7, 1, 30, tzinfo=timezone.utc).isoformat()
    hb._check_reminder_nags()
    assert spoken == []
    assert posts == []


def test_renags_after_interval_elapses(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    # now (10:00 +08:00) is 02:00 UTC; last nag 3 hours before that clears
    # the 120-minute interval.
    hb._reminder_nag_last["t1"] = datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc).isoformat()
    hb._check_reminder_nags()
    assert len(spoken) == 1


def test_prunes_completed_reminder_from_state(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._reminder_nag_last["stale-id"] = datetime.now(timezone.utc).isoformat()
    hb._check_reminder_nags()
    assert hb._reminder_nag_last == {}
    assert spoken == []


def test_multiple_reminders_each_nagged_independently(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod, "_fetch_due_reminders", lambda: [
        {"id": "t1", "title": "Renew passport", "due": "x"},
        {"id": "t2", "title": "Pay rent", "due": "y"},
    ])
    spoken = []
    hb = _hb(tmp_path, monkeypatch, spoken)
    hb._check_reminder_nags()
    assert len(spoken) == 2
    assert {"t1", "t2"} == set(hb._reminder_nag_last.keys())
