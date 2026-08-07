"""voice/heartbeat.py::_process_inbox — routes inbox summaries to notices."""
from __future__ import annotations

import sys
import types

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {"timezone_offset_hours": 8, "inbox_processing_enabled": True}


def _summary(**over):
    base = {
        "path": "lectures/CS101/2026-07-07_intro.md", "type": "lecture", "name": "CS101",
        "subcategory": "", "title": "Intro to Threads", "source": "slides.pptx",
        "deadlines": [{"due_date": "2026-08-01", "title": "A1", "course": "CS101", "source": "inbox:slides.pptx:2026-08-01"}],
        "tldr": ["Threads run concurrently"], "date": "2026-07-07", "study_cards": 5,
        "roadmap_notice": "Roadmap ready: CS101 — Intro to Threads",
    }
    base.update(over)
    return base


def _stub_inbox(monkeypatch, summaries):
    mod = types.ModuleType("core.inbox")
    mod.process_new_files = lambda: summaries
    mod.refresh_daily_timeline = lambda: None
    monkeypatch.setitem(sys.modules, "core.inbox", mod)
    pkg = sys.modules.get("core") or types.ModuleType("core")
    monkeypatch.setattr(pkg, "inbox", mod, raising=False)
    monkeypatch.setitem(sys.modules, "core", pkg)


def _stub_deadlines(monkeypatch, promoted=0):
    mod = types.ModuleType("core.deadlines")
    calls = []
    mod.promote = lambda items: (calls.append(items), promoted)[1]
    monkeypatch.setitem(sys.modules, "core.deadlines", mod)
    pkg = sys.modules.get("core") or types.ModuleType("core")
    monkeypatch.setattr(pkg, "deadlines", mod, raising=False)
    monkeypatch.setitem(sys.modules, "core", pkg)
    return calls


def _env(tmp_path, monkeypatch, conf=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_posts_lecture_summary_and_roadmap_notice(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_inbox(monkeypatch, [_summary()])
    calls = _stub_deadlines(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()
    assert any("Intro to Threads" in p for p in posts)
    assert any("Roadmap ready" in p for p in posts)
    assert calls[0][0]["title"] == "A1"


def test_posts_project_summary_without_roadmap(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_inbox(monkeypatch, [_summary(type="project", name="capstone", roadmap_notice=None, deadlines=[])])
    _stub_deadlines(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()
    assert any("capstone" in p.lower() or "Intro to Threads" in p for p in posts)
    assert not any("Roadmap ready" in p for p in posts)


def test_no_new_files_posts_nothing(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_inbox(monkeypatch, [])
    _stub_deadlines(monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()
    assert posts == []


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, inbox_processing_enabled=False))

    def _boom():
        raise AssertionError("must not process when disabled")

    _stub_inbox(monkeypatch, [])
    import sys as _s
    _s.modules["core.inbox"].process_new_files = _boom
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()
    assert posts == []


def test_processing_error_does_not_raise(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    mod = types.ModuleType("core.inbox")

    def _boom():
        raise RuntimeError("bad pptx")

    mod.process_new_files = _boom
    mod.refresh_daily_timeline = lambda: None
    monkeypatch.setitem(sys.modules, "core.inbox", mod)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()  # must not raise
    assert posts == []


def test_lecture_summary_generates_review_cards(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_inbox(monkeypatch, [_summary()])  # type="lecture", name="CS101"
    _stub_deadlines(monkeypatch)

    added = []
    quiz_mod = types.ModuleType("agents.quiz_generator")
    quiz_mod.run = lambda from_path=None: [{"q": "Q1", "a": "A1", "level": "recall"}]
    monkeypatch.setitem(sys.modules, "agents.quiz_generator", quiz_mod)
    pkg = sys.modules.get("agents") or types.ModuleType("agents")
    pkg.quiz_generator = quiz_mod
    monkeypatch.setitem(sys.modules, "agents", pkg)

    import voice.spaced_repetition as sr
    monkeypatch.setattr(sr, "add_cards", lambda course, cards, **k: added.append((course, cards)) or len(cards))

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()

    assert added == [("CS101", [{"q": "Q1", "a": "A1", "level": "recall"}])]


def test_project_summary_does_not_generate_cards(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    _stub_inbox(monkeypatch, [_summary(type="project", name="capstone", roadmap_notice=None, deadlines=[])])
    _stub_deadlines(monkeypatch)

    called = []
    quiz_mod = types.ModuleType("agents.quiz_generator")
    quiz_mod.run = lambda from_path=None: (called.append(1), [])[1]
    monkeypatch.setitem(sys.modules, "agents.quiz_generator", quiz_mod)

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._process_inbox()
    assert called == []
