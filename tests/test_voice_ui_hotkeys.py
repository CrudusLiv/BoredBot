# tests/test_voice_ui_hotkeys.py
"""UI hotkey bindings are configurable and injected into the served page."""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from voice import ui_server
    return TestClient(ui_server.app)


def _hotkeys(html: str) -> dict:
    m = re.search(r"const VESPER_HOTKEYS = (\{.*?\});", html, re.S)
    assert m, "VESPER_HOTKEYS not injected"
    return json.loads(m.group(1))


def test_defaults_preserve_current_behavior():
    from voice import config as cfg
    assert cfg.DEFAULTS["ui_dock_hotkey"] == "right"
    assert cfg.DEFAULTS["ui_undock_hotkey"] == "left"
    assert cfg.DEFAULTS["ui_confirm_yes_hotkey"] == "y"
    assert cfg.DEFAULTS["ui_confirm_no_hotkey"] == "n"


def test_index_injects_hotkeys(client, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS})
    hk = _hotkeys(client.get("/").text)
    assert hk["dock"] == "right"
    assert hk["undock"] == "left"


def test_index_honors_overridden_hotkey(client, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS, "ui_dock_hotkey": "shift+f"})
    assert _hotkeys(client.get("/").text)["dock"] == "shift+f"


def test_hotkeys_are_settings_allowlisted():
    from voice import ui_server
    for key in ("ui_dock_hotkey", "ui_undock_hotkey",
                "ui_confirm_yes_hotkey", "ui_confirm_no_hotkey"):
        assert key in ui_server._SETTINGS_ALLOWED
