"""Tests for voice/idle.py — Windows GetLastInputInfo wrapper (fail-open)."""
from __future__ import annotations

import sys

from voice import idle


def test_returns_float_or_none():
    """On any platform the call either yields a non-negative float or None —
    it must never raise."""
    result = idle.get_idle_seconds()
    assert result is None or (isinstance(result, float) and result >= 0.0)


def test_non_windows_returns_none(monkeypatch):
    monkeypatch.setattr(idle.sys, "platform", "linux")
    assert idle.get_idle_seconds() is None


def test_api_failure_returns_none(monkeypatch):
    """If GetLastInputInfo reports failure (returns 0), fail open with None."""
    if sys.platform != "win32":
        return  # ctypes.windll doesn't exist off Windows; covered by test above

    import ctypes

    class _FakeUser32:
        @staticmethod
        def GetLastInputInfo(_ref):
            return 0  # BOOL FALSE — API failure

    monkeypatch.setattr(ctypes, "windll", type("W", (), {
        "user32": _FakeUser32,
        "kernel32": ctypes.windll.kernel32,
    }))
    assert idle.get_idle_seconds() is None


def test_exception_returns_none(monkeypatch):
    """Any unexpected exception inside the OS call degrades to None."""
    if sys.platform != "win32":
        return

    import ctypes

    class _Boom:
        def __getattr__(self, name):
            raise OSError("boom")

    monkeypatch.setattr(ctypes, "windll", _Boom())
    assert idle.get_idle_seconds() is None
