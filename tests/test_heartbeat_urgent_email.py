"""voice/heartbeat.py::_check_urgent_email — id-deduped, keyword-triggered
replacement for the old _tick()-based 'N new messages' announcement, which
re-fired on every count change regardless of whether anything was urgent."""
from __future__ import annotations

import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "urgent_email_enabled": True}


def _emails(*rows):
    """rows: (id, subject, snippet) tuples."""
    return [
        {"id": i, "subject": s, "snippet": sn, "from": "sender@example.com", "date": "2026-08-07"}
        for i, s, sn in rows
    ]


def _stub_gmail_int(monkeypatch, emails):
    mod = types.ModuleType("integrations.gmail_int")
    mod.list_recent = lambda days=1, max_results=20: emails
    monkeypatch.setitem(sys.modules, "integrations.gmail_int", mod)
    pkg = sys.modules.get("integrations") or types.ModuleType("integrations")
    monkeypatch.setattr(pkg, "gmail_int", mod, raising=False)
    monkeypatch.setitem(sys.modules, "integrations", pkg)


def _env(tmp_path, monkeypatch, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_for_new_urgent_email(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_gmail_int(monkeypatch, _emails(("m1", "Action required: invoice", "")))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_urgent_email()
    assert len(posts) == 1
    assert "invoice" in posts[0]
    assert "m1" in hb._seen_urgent_email_ids


def test_non_urgent_email_does_not_post(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_gmail_int(monkeypatch, _emails(("m1", "Weekly newsletter", "")))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_urgent_email()
    assert posts == []
    assert hb._seen_urgent_email_ids == []


def test_matches_on_snippet_as_well_as_subject(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_gmail_int(monkeypatch, _emails(("m1", "Re: project", "please respond by Friday")))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_urgent_email()
    assert len(posts) == 1


def test_already_seen_id_does_not_refire(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_gmail_int(monkeypatch, _emails(("m1", "URGENT: server down", "")))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._seen_urgent_email_ids = ["m1"]
    hb._check_urgent_email()
    assert posts == []


def test_seen_ids_persist_across_instances(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_gmail_int(monkeypatch, _emails(("m1", "urgent: renewal", "")))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_urgent_email()
    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert "m1" in hb2._seen_urgent_email_ids


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, urgent_email_enabled=False))

    def _boom(days=1, max_results=20):
        raise AssertionError("must not be called when disabled")

    _stub_gmail_int(monkeypatch, [])
    sys.modules["integrations.gmail_int"].list_recent = _boom
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_urgent_email()
    assert posts == []


def test_fetch_error_does_not_raise(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    mod = types.ModuleType("integrations.gmail_int")

    def _boom(days=1, max_results=20):
        raise RuntimeError("gmail unavailable")

    mod.list_recent = _boom
    monkeypatch.setitem(sys.modules, "integrations.gmail_int", mod)
    pkg = sys.modules.get("integrations") or types.ModuleType("integrations")
    monkeypatch.setattr(pkg, "gmail_int", mod, raising=False)
    monkeypatch.setitem(sys.modules, "integrations", pkg)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_urgent_email()  # must not raise
    assert posts == []


def test_cap_keeps_most_recent_500_in_order(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_gmail_int(monkeypatch, _emails(("new1", "urgent: new", "")))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._seen_urgent_email_ids = [f"seed:{i}" for i in range(500)]
    hb._check_urgent_email()
    assert len(hb._seen_urgent_email_ids) == 500
    assert "new1" in hb._seen_urgent_email_ids
    assert "seed:0" not in hb._seen_urgent_email_ids
