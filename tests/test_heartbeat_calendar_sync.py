"""voice/heartbeat.py::_check_calendar_sync — reuses core.gcal_sync.run()."""
from __future__ import annotations

import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "gcal_sync_enabled": True}


def _stub_gcal_sync(monkeypatch, run_fn):
    mod = types.ModuleType("core.gcal_sync")
    mod.run = run_fn
    monkeypatch.setitem(sys.modules, "core.gcal_sync", mod)
    core_pkg = sys.modules.get("core") or types.ModuleType("core")
    core_pkg.gcal_sync = mod
    monkeypatch.setitem(sys.modules, "core", core_pkg)


def test_posts_notice_when_events_created(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    _stub_gcal_sync(monkeypatch, lambda: 2)

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_calendar_sync()

    assert posts == ["Calendar sync: created 2 new events."]


def test_no_notice_when_nothing_created(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    _stub_gcal_sync(monkeypatch, lambda: 0)

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_calendar_sync()

    assert posts == []


def test_disabled_skips_entirely(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF, gcal_sync_enabled=False))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))

    def _boom():
        raise AssertionError("gcal_sync.run() must not be called when disabled")

    _stub_gcal_sync(monkeypatch, _boom)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_calendar_sync()
    assert posts == []


def test_sync_error_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))

    def _boom():
        raise RuntimeError("network down")

    _stub_gcal_sync(monkeypatch, _boom)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_calendar_sync()  # must not raise
    assert posts == []
