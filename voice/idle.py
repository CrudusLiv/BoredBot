"""Idle/activity signal — thin ctypes wrapper around Windows GetLastInputInfo.

Fail-open by design: get_idle_seconds() returns None whenever the signal is
unavailable (non-Windows, API failure, any exception). Callers must treat
None as "signal unavailable this poll" and never expect an exception.
"""
from __future__ import annotations

import ctypes
import sys


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_idle_seconds() -> float | None:
    """Seconds since last keyboard/mouse input. None if the OS call fails
    (fails open — caller must treat None as 'signal unavailable', never raise)."""
    if sys.platform != "win32":
        return None
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick_count = ctypes.windll.kernel32.GetTickCount()
        # Both counters are uint32 from the same tick source; modulo handles
        # the ~49.7-day GetTickCount wraparound correctly.
        millis = (tick_count - info.dwTime) % (2 ** 32)
        return millis / 1000.0
    except Exception:
        return None
