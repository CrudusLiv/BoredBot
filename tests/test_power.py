"""voice/power.py -- fail-open AC power / battery signal."""
from __future__ import annotations

import sys

from voice import power


def test_interpret_on_ac_with_percent():
    assert power._interpret(1, 80) == {"on_ac": True, "percent": 80}


def test_interpret_on_battery_with_percent():
    assert power._interpret(0, 50) == {"on_ac": False, "percent": 50}


def test_interpret_unknown_percent_is_none():
    assert power._interpret(1, 255) == {"on_ac": True, "percent": None}


def test_interpret_unknown_ac_returns_none():
    assert power._interpret(255, 80) is None


def test_get_power_status_none_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert power.get_power_status() is None


def test_get_power_status_shape_on_this_machine():
    """Smoke: whatever the OS reports, it's None or a well-formed dict."""
    status = power.get_power_status()
    if status is None:
        return
    assert set(status) == {"on_ac", "percent"}
    assert isinstance(status["on_ac"], bool)
    assert status["percent"] is None or isinstance(status["percent"], int)
