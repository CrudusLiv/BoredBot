"""voice/heartbeat.py::_check_github_digest — dedup via self._seen_pr_event_ids."""
from __future__ import annotations

import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "github_digest_enabled": True}


def _events(*ids):
    return [
        {"id": i, "kind": "pr_opened", "repo": "me/repo", "pr_number": n, "pr_title": f"PR {n}"}
        for n, i in enumerate(ids, start=1)
    ]


def _stub_github_int(monkeypatch, events):
    mod = types.ModuleType("integrations.github_int")
    mod.recent_pr_events = lambda since=None: events
    monkeypatch.setitem(sys.modules, "integrations.github_int", mod)
    pkg = sys.modules.get("integrations") or types.ModuleType("integrations")
    pkg.github_int = mod
    monkeypatch.setitem(sys.modules, "integrations", pkg)


def _env(tmp_path, monkeypatch, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_digest_for_new_events(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_github_int(monkeypatch, _events("open:me/repo:1"))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_github_digest()
    assert len(posts) == 1
    assert "PR 1" in posts[0]


def test_dedupes_already_seen_events(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_github_int(monkeypatch, _events("open:me/repo:1"))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._seen_pr_event_ids = ["open:me/repo:1"]
    hb._check_github_digest()
    assert posts == []


def test_seen_ids_persist_across_instances(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_github_int(monkeypatch, _events("open:me/repo:1"))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_github_digest()
    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert "open:me/repo:1" in hb2._seen_pr_event_ids


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, github_digest_enabled=False))

    def _boom(since=None):
        raise AssertionError("must not be called when disabled")

    _stub_github_int(monkeypatch, [])
    import sys as _s
    _s.modules["integrations.github_int"].recent_pr_events = _boom
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_github_digest()
    assert posts == []


def test_fetch_error_does_not_raise(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    mod = types.ModuleType("integrations.github_int")

    def _boom(since=None):
        raise RuntimeError("rate limited")

    mod.recent_pr_events = _boom
    monkeypatch.setitem(sys.modules, "integrations.github_int", mod)
    pkg = sys.modules.get("integrations") or types.ModuleType("integrations")
    pkg.github_int = mod
    monkeypatch.setitem(sys.modules, "integrations", pkg)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_github_digest()  # must not raise
    assert posts == []


def test_cap_keeps_most_recent_500_in_order(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_github_int(monkeypatch, _events("new:me/repo:1"))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    seeded = [f"seed:{i}" for i in range(500)]
    hb._seen_pr_event_ids = list(seeded)
    hb._check_github_digest()
    assert len(hb._seen_pr_event_ids) == 500
    assert "new:me/repo:1" in hb._seen_pr_event_ids
    assert seeded[0] not in hb._seen_pr_event_ids
