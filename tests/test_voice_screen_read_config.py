"""Tests for the screen-read feature's voice/config.py DEFAULTS entries."""
from __future__ import annotations

from voice import config


def test_screen_read_defaults_present_and_disabled_by_default():
    assert config.DEFAULTS["screen_read_enabled"] is False


def test_screen_read_hotkey_defaults_are_distinct_strings():
    keys = [
        config.DEFAULTS["screen_read_capture_hotkey"],
        config.DEFAULTS["screen_read_ask_hotkey"],
        config.DEFAULTS["screen_read_copy_hotkey"],
        config.DEFAULTS["screen_read_dismiss_hotkey"],
    ]
    assert all(isinstance(k, str) and k for k in keys)
    assert len(set(keys)) == len(keys)  # no two hotkeys collide
