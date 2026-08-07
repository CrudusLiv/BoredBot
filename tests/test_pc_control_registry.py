"""voice/tools/__init__.py — pc_control tools must be registered and
dispatchable through the same REGISTRY/dispatch() path every other tool
uses, so brain.py needs no pc_control-specific code."""
from __future__ import annotations

from unittest.mock import patch

from voice import tools


def test_all_pc_control_tools_are_registered():
    names = {t["name"] for t in tools.REGISTRY}
    assert {"media_control", "set_volume", "launch_app", "list_windows", "focus_window"} <= names


def test_dispatch_routes_to_media_control():
    with patch("win32api.keybd_event"):
        result = tools.dispatch("media_control", {"action": "mute"})
    assert "mute" in result.lower()


def test_dispatch_routes_to_list_windows():
    with patch("win32gui.EnumWindows", side_effect=lambda cb, extra: None):
        result = tools.dispatch("list_windows", {})
    assert isinstance(result, str)
