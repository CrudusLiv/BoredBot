"""Tests for feed side-effects inside dashboard.notify()."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))


def test_ok_tick_not_appended_to_feed():
    appended = []
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or {}):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("heartbeat_tick", {"status": "ok", "failing": []})
    assert "heartbeat_tick" not in appended


def test_degraded_tick_appended_to_feed():
    appended = []
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or {"title": "t", "body": "b"}):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("heartbeat_tick", {"status": "degraded", "failing": ["gmail"]})
    assert "heartbeat_tick" in appended


def test_deadline_reply_not_appended_to_feed():
    appended = []
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or {}):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("deadline_reply", {"text": "reply"})
    assert "deadline_reply" not in appended


def test_deadline_24h_appended_to_feed():
    appended = []
    payload = {"course": "CS101", "title": "Lab", "due": "2026-06-05", "days": 1}
    record = {"title": "[CS101] Lab", "body": "due 2026-06-05"}
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or record):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("deadline_24h", payload)
    assert "deadline_24h" in appended


def test_error_appended_to_feed():
    appended = []
    record = {"title": "Error in x", "body": "boom"}
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or record):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("error", {"script": "x", "trace": "boom"})
    assert "error" in appended


def test_morning_digest_appended_to_feed():
    appended = []
    record = {"title": "Morning — Thu", "body": "..."}
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or record):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("morning_digest", {"body": "good morning"})
    assert "morning_digest" in appended


def test_feed_failure_does_not_raise():
    with patch("core.feed.append", side_effect=OSError("disk full")):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("morning_digest", {"body": "hello"})


def test_notify_idempotent_on_repeated_calls():
    appended = []
    with patch("core.feed.append", side_effect=lambda k, p: appended.append(k) or {"title": "t", "body": "b"}):
        from core import dashboard
        import importlib; importlib.reload(dashboard)
        dashboard.notify("morning_digest", {"body": "first"})
        dashboard.notify("morning_digest", {"body": "second"})
    assert appended.count("morning_digest") == 2
