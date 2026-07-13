"""voice/heartbeat.py::_check_habits — thin wrapper posting habits.py's own output."""
from __future__ import annotations

import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "habits_enabled": True}


def _stub_habits(monkeypatch, *, auto_checked=None, nudge_due=False, unchecked=None):
    mod = types.ModuleType("core.habits")
    mod.auto_check = lambda snapshot: (auto_checked or [])
    mod.should_nudge = lambda now=None: nudge_due
    mod.unchecked_pillars = lambda: (unchecked or [])
    mod.nudge_message = lambda u: ("Habit nudge", f"Still open: {', '.join(u)}.")
    marked = []
    mod.mark_nudged = lambda: marked.append(True)
    monkeypatch.setitem(sys.modules, "core.habits", mod)
    pkg = sys.modules.get("core") or types.ModuleType("core")
    monkeypatch.setattr(pkg, "habits", mod, raising=False)
    monkeypatch.setitem(sys.modules, "core", pkg)
    return marked


def _stub_pushes(monkeypatch, pushes=None):
    mod = types.ModuleType("integrations.github_int")
    mod.recent_pushes = lambda days=1: (pushes or [])
    monkeypatch.setitem(sys.modules, "integrations.github_int", mod)
    pkg = sys.modules.get("integrations") or types.ModuleType("integrations")
    monkeypatch.setattr(pkg, "github_int", mod, raising=False)
    monkeypatch.setitem(sys.modules, "integrations", pkg)


def _env(tmp_path, monkeypatch, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_auto_checked_pillars(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_habits(monkeypatch, auto_checked=["Lectures", "Sleep"])
    _stub_pushes(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_habits()
    assert any("Lectures" in p and "Sleep" in p for p in posts)


def test_posts_nudge_when_due(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    marked = _stub_habits(monkeypatch, nudge_due=True, unchecked=["Sleep"])
    _stub_pushes(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_habits()
    assert any("Still open: Sleep" in p for p in posts)
    assert marked == [True]


def test_no_nudge_when_nothing_unchecked(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_habits(monkeypatch, nudge_due=True, unchecked=[])
    _stub_pushes(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_habits()
    assert posts == []


def test_no_vault_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: None)

    def _boom(snapshot):
        raise AssertionError("must not run without a vault")

    _stub_habits(monkeypatch)
    import sys as _s
    _s.modules["core.habits"].auto_check = _boom
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_habits()
    assert posts == []


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, habits_enabled=False))
    _stub_habits(monkeypatch, auto_checked=["Lectures"])
    _stub_pushes(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_habits()
    assert posts == []
