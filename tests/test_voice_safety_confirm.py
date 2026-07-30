"""Tests for voice.safety.confirm_with_reason's HTTP-first, then-fallback
behavior once tool dispatch can happen in a separate process from ui_server."""
from __future__ import annotations

import json
import os
from urllib.error import URLError

import pytest

from voice import safety


@pytest.fixture(autouse=True)
def _not_paused(monkeypatch):
    monkeypatch.setattr("voice.killswitch.is_paused", lambda: False)


@pytest.fixture(autouse=True)
def _fixed_port(monkeypatch):
    monkeypatch.setattr(
        "voice.config.load",
        lambda: {"confirm_timeout_seconds": 30, "ui_port": 7070},
    )


def test_paused_short_circuits_before_any_http_call(monkeypatch):
    monkeypatch.setattr("voice.killswitch.is_paused", lambda: True)
    called = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: called.append(1))
    approved, reason = safety.confirm_with_reason("create_note", {"path": "x.md"})
    assert (approved, reason) == (False, "paused")
    assert called == []


def test_http_bridge_success_returns_server_decision(monkeypatch):
    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"approved": True, "reason": "user"}).encode()

    monkeypatch.setenv("VESPER_UI_TOKEN", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())
    approved, reason = safety.confirm_with_reason("create_note", {"path": "x.md"})
    assert (approved, reason) == (True, "user")


def test_http_bridge_explicit_deny_normalizes_reason_to_cancelled(monkeypatch):
    """The orb UI reports raw reason='user' for both approve and explicit
    deny votes (voice/confirm.py's resolve() always sets pending.reason =
    'user'). confirm_with_reason's contract says 'user' only ever
    accompanies approved=True, so an explicit deny must be translated to
    'cancelled', never passed through verbatim."""
    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"approved": False, "reason": "user"}).encode()

    monkeypatch.setenv("VESPER_UI_TOKEN", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())
    approved, reason = safety.confirm_with_reason("create_note", {"path": "x.md"})
    assert (approved, reason) == (False, "cancelled")


def test_http_bridge_unreachable_falls_back_to_console(monkeypatch):
    def _raise(*a, **k):
        raise URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    monkeypatch.setattr(
        "voice.safety._console_confirm", lambda *a, **k: (True, "user")
    )
    approved, reason = safety.confirm_with_reason("create_note", {"path": "x.md"})
    assert (approved, reason) == (True, "user")


def test_http_bridge_sends_token_header(monkeypatch):
    seen = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"approved": False, "reason": "user"}).encode()

    def _fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        return _FakeResp()

    monkeypatch.setenv("VESPER_UI_TOKEN", "test-token-123")
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    safety.confirm_with_reason("forget_fact", {"key": "x"})
    assert seen["url"] == "http://127.0.0.1:7070/internal/confirm"
    assert seen["headers"].get("X-vesper-token") == "test-token-123"
