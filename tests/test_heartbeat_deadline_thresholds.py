"""voice/heartbeat.py::_check_deadline_thresholds — per-key threshold dedup."""
from __future__ import annotations

import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "deadline_threshold_enabled": True}


def _item(key="CS101|A1|2026-08-01", bucket="urgent", course="CS101", title="Assignment 1"):
    return {"key": key, "bucket": bucket, "course": course, "title": title, "days": 1}


def _stub_imminent(monkeypatch, actionable_items):
    mod = types.ModuleType("core.imminent")
    mod.scan = lambda now=None: {}
    mod.actionable = lambda buckets: actionable_items
    monkeypatch.setitem(sys.modules, "core.imminent", mod)
    pkg = sys.modules.get("core") or types.ModuleType("core")
    pkg.imminent = mod
    monkeypatch.setitem(sys.modules, "core", pkg)


def _env(tmp_path, monkeypatch, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_on_first_sighting_of_a_threshold(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_imminent(monkeypatch, [_item(bucket="urgent")])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_deadline_thresholds()
    assert len(posts) == 1
    assert "Assignment 1" in posts[0]
    assert hb._deadline_fired["CS101|A1|2026-08-01"] == ["24h"]


def test_same_threshold_does_not_refire(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_imminent(monkeypatch, [_item(bucket="urgent")])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._deadline_fired = {"CS101|A1|2026-08-01": ["24h"]}
    hb._check_deadline_thresholds()
    assert posts == []


def test_escalating_bucket_fires_again(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_imminent(monkeypatch, [_item(bucket="overdue")])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._deadline_fired = {"CS101|A1|2026-08-01": ["72h", "24h"]}
    hb._check_deadline_thresholds()
    assert len(posts) == 1
    assert hb._deadline_fired["CS101|A1|2026-08-01"] == ["72h", "24h", "overdue"]


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, deadline_threshold_enabled=False))

    def _boom(buckets):
        raise AssertionError("must not be called when disabled")

    _stub_imminent(monkeypatch, [])
    import sys as _s
    _s.modules["core.imminent"].actionable = _boom
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_deadline_thresholds()
    assert posts == []


def test_scan_error_does_not_raise(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    mod = types.ModuleType("core.imminent")

    def _boom(now=None):
        raise RuntimeError("bad vault path")

    mod.scan = _boom
    mod.actionable = lambda buckets: []
    monkeypatch.setitem(sys.modules, "core.imminent", mod)
    pkg = sys.modules.get("core") or types.ModuleType("core")
    pkg.imminent = mod
    monkeypatch.setitem(sys.modules, "core", pkg)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_deadline_thresholds()  # must not raise
    assert posts == []
