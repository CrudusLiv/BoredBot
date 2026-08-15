"""voice/heartbeat.py::Heartbeat._run_scheduled -- per-task interval
registry. Each task in _SCHEDULE fires independently once its own
interval (config-overridable for gcal_sync/github_digest, else a fixed
default) has elapsed, tracked via time.monotonic() so a task that raises
still advances its own last-run time instead of being retried every poll."""
from __future__ import annotations

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8}


def _hb(monkeypatch, tmp_path, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF, **(conf or {})))
    return Heartbeat(interval_minutes=30, idle_fn=lambda: None)


def _stub_all_tasks(monkeypatch, hb, calls: dict[str, int]):
    """Replace every task method referenced in _SCHEDULE with a call counter."""
    for _name, method_name, _default_min, _cfg_key in hb_mod.Heartbeat._SCHEDULE:
        calls.setdefault(method_name, 0)

        def _make(mn):
            def _fn():
                calls[mn] += 1
            return _fn

        monkeypatch.setattr(hb, method_name, _make(method_name))


def test_first_run_fires_every_task_immediately(tmp_path, monkeypatch):
    hb = _hb(monkeypatch, tmp_path)
    calls: dict[str, int] = {}
    _stub_all_tasks(monkeypatch, hb, calls)

    hb._run_scheduled()

    assert all(n == 1 for n in calls.values())


def test_task_not_due_is_skipped_others_still_run(tmp_path, monkeypatch):
    hb = _hb(monkeypatch, tmp_path)
    calls: dict[str, int] = {}
    _stub_all_tasks(monkeypatch, hb, calls)

    t = [1000.0]
    monkeypatch.setattr(hb_mod.time, "monotonic", lambda: t[0])
    hb._run_scheduled()  # baseline: everything fires once, last_run = 1000.0

    # 4 minutes later: gcal_sync/github_digest (5 min default) not due yet,
    # everything else (30 min default) also not due -- nothing should fire.
    t[0] = 1000.0 + 4 * 60
    for c in calls:
        calls[c] = 0
    hb._run_scheduled()
    assert all(n == 0 for n in calls.values())

    # 6 minutes later (10 total): gcal_sync/github_digest ARE due (5 min),
    # the 30-min-default tasks are not.
    t[0] = 1000.0 + 10 * 60
    hb._run_scheduled()
    assert calls["_check_calendar_sync"] == 1
    assert calls["_check_github_digest"] == 1
    assert calls["_check_job_alerts"] == 0


def test_config_override_changes_interval(tmp_path, monkeypatch):
    hb = _hb(monkeypatch, tmp_path, conf={
        "gcal_sync_interval_minutes": 1,
        "github_digest_interval_minutes": 1,
    })
    calls: dict[str, int] = {}
    _stub_all_tasks(monkeypatch, hb, calls)

    t = [0.0]
    monkeypatch.setattr(hb_mod.time, "monotonic", lambda: t[0])
    hb._run_scheduled()

    t[0] = 90.0  # 1.5 minutes later -- past the 1-min override
    hb._run_scheduled()
    assert calls["_check_calendar_sync"] == 2
    assert calls["_check_github_digest"] == 2


def test_nudges_default_interval_is_well_under_nudge_window(tmp_path, monkeypatch):
    """nudges must poll faster than the default 15-minute nudge_minutes
    window, or an event's heads-up can close between checks and never get
    caught (was a 30-minute gate; regression guard for the fix)."""
    hb = _hb(monkeypatch, tmp_path)
    calls: dict[str, int] = {}
    _stub_all_tasks(monkeypatch, hb, calls)

    t = [0.0]
    monkeypatch.setattr(hb_mod.time, "monotonic", lambda: t[0])
    hb._run_scheduled()

    t[0] = 6 * 60.0  # 6 minutes later -- past the 5-min default, still
    calls["_check_nudges"] = 0             # well inside a 15-min window
    hb._run_scheduled()
    assert calls["_check_nudges"] == 1


def test_nudges_interval_is_config_overridable(tmp_path, monkeypatch):
    hb = _hb(monkeypatch, tmp_path, conf={"nudge_check_interval_minutes": 1})
    calls: dict[str, int] = {}
    _stub_all_tasks(monkeypatch, hb, calls)

    t = [0.0]
    monkeypatch.setattr(hb_mod.time, "monotonic", lambda: t[0])
    hb._run_scheduled()

    t[0] = 90.0  # 1.5 minutes later -- past the 1-min override
    hb._run_scheduled()
    assert calls["_check_nudges"] == 2


def test_task_that_raises_still_advances_last_run(tmp_path, monkeypatch, capsys):
    hb = _hb(monkeypatch, tmp_path)
    calls: dict[str, int] = {}
    _stub_all_tasks(monkeypatch, hb, calls)

    def _boom():
        calls["_check_job_alerts"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(hb, "_check_job_alerts", _boom)

    t = [0.0]
    monkeypatch.setattr(hb_mod.time, "monotonic", lambda: t[0])
    hb._run_scheduled()  # raises internally, caught -- last_run still set

    t[0] = 60.0  # 1 minute later -- nowhere near the 30-min default interval
    hb._run_scheduled()

    assert calls["_check_job_alerts"] == 1  # not retried early
