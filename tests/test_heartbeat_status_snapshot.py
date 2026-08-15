"""voice/heartbeat.py::Heartbeat.status_snapshot — per-task status for the
orb's Heartbeat panel. Daily-fixed-time tasks (morning_briefing,
evening_wrap, git_todo_summary, build_watch, vault_daily_rollup) must
report their real next occurrence at a configured time-of-day, not the
next 30-minute _SCHEDULE gate-check -- that gate is just how often the
"is it time yet" check runs, not how often the task actually fires."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "briefing_time": "09:00"}

# Fixed instant: 2026-07-07T02:00:00Z == 2026-07-07 10:00 in UTC+8.
_FIXED_UTC = datetime(2026, 7, 7, 2, 0, tzinfo=timezone.utc)


class _FakeDateTime(datetime):
    """Subclasses real datetime (not a bare stub) so status_snapshot's use
    of datetime.combine()/.fromisoformat() keeps working -- only .now() is
    overridden, driven by a module-level _NOW so each test can move the
    clock without redefining the whole class."""
    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is None else _NOW.astimezone(tz)


_NOW = _FIXED_UTC


def _env(tmp_path, monkeypatch, conf=None, hour=10, minute=0):
    global _NOW
    _NOW = datetime(2026, 7, 7, hour, minute, tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    monkeypatch.setattr(hb_mod, "datetime", _FakeDateTime)


def _hb(tmp_path, monkeypatch):
    return Heartbeat(interval_minutes=30, idle_fn=lambda: None)


def _task(snapshot, name):
    return next(t for t in snapshot["tasks"] if t["name"] == name)


def test_daily_task_before_target_time_not_yet_done(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, hour=8, minute=0)
    hb = _hb(tmp_path, monkeypatch)
    t = _task(hb.status_snapshot(), "morning_briefing")
    assert t["schedule_kind"] == "daily"
    assert t["cadence_label"] == "daily at 09:00"
    assert t["last_run"] is None
    assert 3500 <= t["due_in_seconds"] <= 3600


def test_daily_task_after_target_time_not_yet_done_is_imminent(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, hour=10, minute=0)
    hb = _hb(tmp_path, monkeypatch)
    t = _task(hb.status_snapshot(), "morning_briefing")
    assert t["due_in_seconds"] == 0


def test_daily_task_done_today_reports_last_run_and_tomorrow_due(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, hour=10, minute=0)
    hb = _hb(tmp_path, monkeypatch)
    hb._briefing_done_date = date(2026, 7, 7)
    t = _task(hb.status_snapshot(), "morning_briefing")
    assert t["last_run"] is not None
    assert t["last_run"].startswith("2026-07-07T09:00:00")
    # ~23h until tomorrow's 09:00.
    assert 82700 <= t["due_in_seconds"] <= 82800


def test_daily_task_done_yesterday_is_due_now(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, hour=10, minute=0)
    hb = _hb(tmp_path, monkeypatch)
    hb._briefing_done_date = date(2026, 7, 6)
    t = _task(hb.status_snapshot(), "morning_briefing")
    assert t["last_run"].startswith("2026-07-06T09:00:00")
    assert t["due_in_seconds"] == 0


def test_interval_task_reports_gate_check_cadence(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, hour=10, minute=0)
    hb = _hb(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.time, "monotonic", lambda: 10_000.0)
    # Ran 5 minutes ago; job_alerts' default interval is 30 minutes.
    hb._last_run["job_alerts"] = 10_000.0 - 5 * 60
    t = _task(hb.status_snapshot(), "job_alerts")
    assert t["schedule_kind"] == "interval"
    assert t["cadence_label"] == "every 30m"
    assert t["last_run"] is not None
    assert 1490 <= t["due_in_seconds"] <= 1500  # ~25 minutes left


def test_enabled_reflects_config(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, conf=dict(CONF, build_watch_enabled=False))
    hb = _hb(tmp_path, monkeypatch)
    assert _task(hb.status_snapshot(), "build_watch")["enabled"] is False
    assert _task(hb.status_snapshot(), "job_alerts")["enabled"] is True


def test_busy_state_passthrough(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    hb = _hb(tmp_path, monkeypatch)
    hb._busy = True
    hb._busy_proc = "valorant-win64-shipping.exe"
    snap = hb.status_snapshot()
    assert snap["busy"] is True
    assert snap["busy_proc"] == "valorant-win64-shipping.exe"
