"""AC power / battery signal — thin ctypes wrapper around Windows
GetSystemPowerStatus.

Fail-open, same contract as voice/idle.py: get_power_status() returns None
whenever the reading is unavailable (non-Windows, API failure, unknown
ACLineStatus, any exception). Callers treat None as "no reading this poll"
and never expect an exception.
"""
from __future__ import annotations

import ctypes
import sys


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def _interpret(ac: int, pct: int) -> dict | None:
    """Map raw GetSystemPowerStatus bytes to {"on_ac", "percent"}.

    ACLineStatus is 1 (online) or 0 (offline); anything else (255 unknown)
    yields None so a caller never fires a bogus transition. BatteryLifePercent
    is 0–100, or 255 when unknown / there's no battery -> percent None."""
    if ac not in (0, 1):
        return None
    return {"on_ac": ac == 1, "percent": None if pct == 255 else int(pct)}


def get_power_status() -> dict | None:
    """{"on_ac": bool, "percent": int | None} or None if unavailable."""
    if sys.platform != "win32":
        return None
    try:
        status = _SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
        return _interpret(status.ACLineStatus, status.BatteryLifePercent)
    except Exception:
        return None
