"""Tests for orb-window reopen helpers in voice/ui_server.py.

ensure_window_open() must launch the app window only when no WS client is
connected (wake-word path); open_window() launches unconditionally (tray)."""
from __future__ import annotations

import pytest

from voice import ui_server


@pytest.fixture
def opened(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(ui_server, "_open_app_window", lambda port: calls.append(port))
    return calls


def test_ensure_opens_when_no_clients(opened, monkeypatch):
    monkeypatch.setattr(ui_server, "_clients", [])
    ui_server.ensure_window_open()
    assert opened == [ui_server._ui_port]


def test_ensure_noop_when_client_connected(opened, monkeypatch):
    monkeypatch.setattr(ui_server, "_clients", [object()])
    ui_server.ensure_window_open()
    assert opened == []


def test_open_window_always_opens(opened, monkeypatch):
    monkeypatch.setattr(ui_server, "_clients", [object()])
    ui_server.open_window()
    assert opened == [ui_server._ui_port]


def test_open_window_uses_port_set_by_start(opened, monkeypatch):
    monkeypatch.setattr(ui_server, "_ui_port", 7171)
    ui_server.open_window()
    assert opened == [7171]
