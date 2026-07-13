"""voice/heartbeat.py::_tick — must not re-post an identical calendar/email/
deadline notice on consecutive ticks (this is what produced the duplicate
Windows toast on launch + first slow tick)."""
from __future__ import annotations

from voice import heartbeat as hb_mod


def _env(monkeypatch, calendar=None, email=None, deadlines=None):
    posts: list[str] = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    monkeypatch.setattr(hb_mod, "_check_calendar", lambda: calendar or [])
    monkeypatch.setattr(hb_mod, "_check_email", lambda: email or [])
    monkeypatch.setattr(hb_mod, "_check_deadlines", lambda: deadlines or [])
    return posts


def test_unchanged_notice_not_reposted_on_next_tick(monkeypatch):
    posts = _env(monkeypatch, calendar=["Calendar: Standup at 09:00"])
    hb_mod._tick()
    hb_mod._tick()
    assert posts == ["Calendar: Standup at 09:00"]


def test_changed_notice_is_reposted(monkeypatch):
    posts = _env(monkeypatch, email=["Email: 1 new message(s) in the last 24h"])
    hb_mod._tick()
    monkeypatch.setattr(hb_mod, "_check_email", lambda: ["Email: 2 new message(s) in the last 24h"])
    hb_mod._tick()
    assert posts == [
        "Email: 1 new message(s) in the last 24h",
        "Email: 2 new message(s) in the last 24h",
    ]


def test_notice_that_disappears_and_returns_is_reposted(monkeypatch):
    posts = _env(monkeypatch, deadlines=["Deadlines: HW1 due"])
    hb_mod._tick()
    monkeypatch.setattr(hb_mod, "_check_deadlines", lambda: [])
    hb_mod._tick()
    monkeypatch.setattr(hb_mod, "_check_deadlines", lambda: ["Deadlines: HW1 due"])
    hb_mod._tick()
    assert posts == ["Deadlines: HW1 due", "Deadlines: HW1 due"]
