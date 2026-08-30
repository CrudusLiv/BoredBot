"""voice/heartbeat.py::_check_google_auth -- posts an URGENT notice when a
Google account's cached sign-in has gone dead, then re-nags no more than
once per 24h until it's reconnected (state in heartbeat_state.json)."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "google_auth_check_enabled": True}


def _stub_google_auth(monkeypatch, *, accounts, status):
    """status: dict label -> status-dict, or a callable(account)->status-dict."""
    mod = types.ModuleType("integrations.google_auth")
    mod.list_accounts = lambda: list(accounts)

    def _account_status(account=None):
        label = account or "primary"
        return status(account) if callable(status) else status[label]

    mod.account_status = _account_status
    monkeypatch.setitem(sys.modules, "integrations.google_auth", mod)
    pkg = sys.modules.get("integrations") or types.ModuleType("integrations")
    monkeypatch.setattr(pkg, "google_auth", mod, raising=False)
    monkeypatch.setitem(sys.modules, "integrations", pkg)
    return mod


def _dead(label):
    return {"account": label, "connected": False, "needs_reconnect": True,
            "detail": "sign-in expired"}


def _ok(label):
    return {"account": label, "connected": True, "needs_reconnect": False,
            "detail": "connected"}


def _env(tmp_path, monkeypatch, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post",
                        lambda text, level="INFO", meta=None: posts.append((level, text)))
    return posts


def _now():
    return datetime.now(cfg.get_timezone())


def test_posts_urgent_notice_when_account_needs_reconnect(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_google_auth(monkeypatch, accounts=[None], status={"primary": _dead("primary")})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_google_auth()
    assert len(posts) == 1
    level, text = posts[0]
    assert level == "URGENT"
    assert "primary" in text


def test_does_not_renotify_within_24h(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_google_auth(monkeypatch, accounts=[None], status={"primary": _dead("primary")})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._google_auth_notified = {"primary": (_now() - timedelta(hours=1)).isoformat()}
    hb._check_google_auth()
    assert posts == []


def test_renotifies_after_24h(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_google_auth(monkeypatch, accounts=[None], status={"primary": _dead("primary")})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._google_auth_notified = {"primary": (_now() - timedelta(hours=25)).isoformat()}
    hb._check_google_auth()
    assert len(posts) == 1


def test_clears_state_once_account_reconnects(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_google_auth(monkeypatch, accounts=[None], status={"primary": _ok("primary")})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._google_auth_notified = {"primary": (_now() - timedelta(hours=1)).isoformat()}
    hb._check_google_auth()
    assert posts == []
    assert "primary" not in hb._google_auth_notified


def test_disabled_flag_skips_the_check(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, conf={**CONF, "google_auth_check_enabled": False})
    _stub_google_auth(monkeypatch, accounts=[None], status={"primary": _dead("primary")})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_google_auth()
    assert posts == []


def test_notifies_each_dead_account(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_google_auth(
        monkeypatch,
        accounts=[None, "jobs"],
        status={"primary": _dead("primary"), "jobs": _dead("jobs")},
    )
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_google_auth()
    labels = " ".join(t for _, t in posts)
    assert "primary" in labels and "jobs" in labels
    assert len(posts) == 2


def test_notified_state_survives_reload(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    _stub_google_auth(monkeypatch, accounts=[None], status={"primary": _dead("primary")})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_google_auth()
    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert "primary" in hb2._google_auth_notified
