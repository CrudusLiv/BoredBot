from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

import pytest


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    # Evict cached module so the next import reads the patched env var.
    import sys as _sys
    _sys.modules.pop("heartbeat.feed", None)
    _sys.modules.pop("feed", None)


def test_append_returns_record():
    from core.feed import append
    rec = append("deadline_24h", {
        "course": "CS101", "title": "Assignment 3", "due": "2026-06-05", "days": 1,
    })
    assert rec["kind"] == "deadline_24h"
    assert rec["title"] == "[CS101] Assignment 3"
    assert rec["body"] == "due 2026-06-05"
    assert rec["priority"] == "high"
    assert rec["read"] is False
    assert "id" in rec
    assert "created_at" in rec


def test_append_caps_at_50():
    from core.feed import append, recent
    for i in range(55):
        append("morning_digest", {"body": f"entry {i}"})
    assert len(recent()) == 50


def test_append_newest_first():
    from core.feed import append, recent
    append("morning_digest", {"body": "first"})
    append("error", {"script": "x", "trace": "boom"})
    items = recent()
    assert items[0]["kind"] == "error"
    assert items[1]["kind"] == "morning_digest"


def test_mark_read_sets_flag():
    from core.feed import append, mark_read, recent
    rec = append("error", {"script": "heartbeat.py", "trace": "oops"})
    result = mark_read(rec["id"])
    assert result is not None
    assert result["read"] is True
    assert recent()[0]["read"] is True


def test_mark_read_unknown_id_returns_none():
    from core.feed import mark_read
    assert mark_read("does-not-exist") is None


def test_recent_respects_limit():
    from core.feed import append, recent
    for i in range(10):
        append("morning_digest", {"body": str(i)})
    assert len(recent(limit=3)) == 3


def test_feed_title_body_deadline_24h():
    from core.feed import _feed_title_body
    title, body = _feed_title_body("deadline_24h", {
        "course": "CS101", "title": "Lab 2", "due": "2026-06-05", "days": 1,
    })
    assert title == "[CS101] Lab 2"
    assert "2026-06-05" in body


def test_feed_title_body_no_course():
    from core.feed import _feed_title_body
    title, body = _feed_title_body("deadline_overdue", {
        "title": "Exam", "due": "2026-06-01", "days": -3,
    })
    assert title == "Exam"
    assert "2026-06-01" in body


def test_feed_title_body_error():
    from core.feed import _feed_title_body
    title, body = _feed_title_body("error", {"script": "heartbeat.py", "trace": "Traceback..."})
    assert "heartbeat.py" in title
    assert "Traceback" in body


def test_feed_title_body_heartbeat_degraded():
    from core.feed import _feed_title_body
    title, body = _feed_title_body("heartbeat_tick", {
        "status": "degraded", "failing": ["gmail", "gcal"],
    })
    assert "degraded" in title.lower() or "System" in title
    assert "gmail" in body


def test_feed_priority_urgent():
    from core.feed import append
    rec = append("error", {"script": "x", "trace": ""})
    assert rec["priority"] == "urgent"


def test_feed_priority_low():
    from core.feed import append
    rec = append("morning_digest", {"body": "hello"})
    assert rec["priority"] == "low"
