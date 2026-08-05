"""Tests for the internal HTTP bridge used by the MCP-server subprocess
to reach the running UI server for confirmation and tool-status events."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # Import fresh so module-level TOKEN/os.environ wiring runs in this test.
    from voice import ui_server
    return TestClient(ui_server.app), ui_server


def test_token_env_var_set_on_import():
    from voice import ui_server
    assert os.environ.get("VESPER_UI_TOKEN") == ui_server.TOKEN


def test_internal_confirm_requires_token(client):
    c, ui_server = client
    resp = c.post("/internal/confirm", json={"tool": "create_note", "args": {}, "timeout_s": 1})
    assert resp.status_code == 401


def test_internal_confirm_returns_request_result(client, monkeypatch):
    c, ui_server = client

    def fake_request(tool, args, timeout_s):
        assert tool == "create_note"
        assert args == {"path": "x.md"}
        assert timeout_s == 5.0
        return True, "user"

    monkeypatch.setattr("voice.confirm.request", fake_request)
    resp = c.post(
        "/internal/confirm",
        json={"tool": "create_note", "args": {"path": "x.md"}, "timeout_s": 5.0},
        headers={"X-Vesper-Token": ui_server.TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"approved": True, "reason": "user"}


def test_internal_tool_event_requires_token(client):
    c, ui_server = client
    resp = c.post("/internal/tool-event", json={"event": {"type": "tool"}})
    assert resp.status_code == 401


def test_internal_tool_event_relays_to_post_event(client, monkeypatch):
    c, ui_server = client
    seen = {}
    monkeypatch.setattr(ui_server, "post_event", lambda event: seen.update(event))
    resp = c.post(
        "/internal/tool-event",
        json={"event": {"type": "tool", "name": "search_vault", "status": "start"}},
        headers={"X-Vesper-Token": ui_server.TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert seen == {"type": "tool", "name": "search_vault", "status": "start"}


def test_post_event_state_also_broadcasts_emotion(monkeypatch):
    from voice import ui_server
    seen = []
    monkeypatch.setattr(ui_server, "_loop", type("L", (), {"call_soon_threadsafe": staticmethod(lambda fn, arg: (fn, seen.append(arg)))})())
    from unittest.mock import Mock
    monkeypatch.setattr(ui_server, "_queue", Mock())
    ui_server.post_event({"type": "state", "value": "thinking"})
    assert seen[0] == {"type": "state", "value": "thinking"}
    assert seen[1] == {"type": "emotion", "tag": "focused", "intensity": 0.7}


def test_post_event_non_state_event_does_not_add_emotion(monkeypatch):
    from voice import ui_server
    seen = []
    monkeypatch.setattr(ui_server, "_loop", type("L", (), {"call_soon_threadsafe": staticmethod(lambda fn, arg: (fn, seen.append(arg)))})())
    from unittest.mock import Mock
    monkeypatch.setattr(ui_server, "_queue", Mock())
    ui_server.post_event({"type": "amplitude", "value": 0.1})
    assert seen == [{"type": "amplitude", "value": 0.1}]
