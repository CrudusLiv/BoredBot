"""voice/heartbeat.py::_check_ambient_notices — MD5-deduped vault notifications."""
from __future__ import annotations

import hashlib
import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "ambient_notifier_enabled": True, "vault_path": ""}


def _notification(rule="dependency_gap", content="No lecture covers Threads yet"):
    return {"type": "gap", "rule": rule, "content": content}


def _stub_ambient(monkeypatch, notifications):
    mod = types.ModuleType("ambient_notifier")
    mod.scan_vault_state = lambda vault_dir: {}
    mod.collect_notifications = lambda state: notifications
    monkeypatch.setitem(sys.modules, "ambient_notifier", mod)
    return mod


def _env(tmp_path, monkeypatch, conf=None, vault=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: vault or tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_new_notification(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_ambient(monkeypatch, [_notification()])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_ambient_notices()
    assert posts == ["No lecture covers Threads yet"]


def test_dedupes_by_md5_of_rule_and_content(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    note = _notification()
    _stub_ambient(monkeypatch, [note])
    nid = hashlib.md5(f"{note['rule']}:{note['content']}".encode()).hexdigest()
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._seen_ambient_ids = [nid]
    hb._check_ambient_notices()
    assert posts == []


def test_cap_keeps_most_recent_200_in_order(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    note = _notification(rule="new_rule", content="fresh notice")
    _stub_ambient(monkeypatch, [note])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    seeded = [f"seed:{i}" for i in range(200)]
    hb._seen_ambient_ids = list(seeded)
    hb._check_ambient_notices()
    nid = hashlib.md5(f"{note['rule']}:{note['content']}".encode()).hexdigest()
    assert len(hb._seen_ambient_ids) == 200
    assert nid in hb._seen_ambient_ids
    assert seeded[0] not in hb._seen_ambient_ids


def test_no_vault_configured_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, vault=None)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: None)

    def _boom(vault_dir):
        raise AssertionError("must not scan when no vault configured")

    _stub_ambient(monkeypatch, [])
    import sys as _s
    _s.modules["ambient_notifier"].scan_vault_state = _boom
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_ambient_notices()
    assert posts == []


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, ambient_notifier_enabled=False))
    _stub_ambient(monkeypatch, [_notification()])
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_ambient_notices()
    assert posts == []


def test_scan_error_does_not_raise(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    mod = types.ModuleType("ambient_notifier")

    def _boom(vault_dir):
        raise RuntimeError("bad vault")

    mod.scan_vault_state = _boom
    mod.collect_notifications = lambda state: []
    monkeypatch.setitem(sys.modules, "ambient_notifier", mod)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_ambient_notices()  # must not raise
    assert posts == []
