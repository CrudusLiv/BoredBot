"""Global silence gate — the one predicate every mic and speaker path checks.

Two independent sources collapse to the same effect: no wake-word detection, no
open microphone, no speech of any kind.

  killswitch  user-set pause; a marker file, so it survives restarts
  busy        a `silence_when_running` process is up (heartbeat sets this)

Silence is total, not merely "she won't interrupt you" — so a silenced Vesper
also cannot hear the `resume duties` phrase. Resume is UI-only: the orb's pause
button or the tray's Resume item.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_busy = False


def set_busy(value: bool) -> None:
    """Called by the heartbeat when a silence_when_running process opens/closes."""
    global _busy
    with _lock:
        _busy = bool(value)


def is_busy() -> bool:
    with _lock:
        return _busy


def is_silenced() -> bool:
    from voice import killswitch
    return killswitch.is_paused() or is_busy()


def reason() -> str:
    """'paused' | 'busy' | '' — for logs and the UI. Killswitch outranks busy:
    it is the deliberate one, and it outlives the process that caused the other."""
    from voice import killswitch
    if killswitch.is_paused():
        return "paused"
    return "busy" if is_busy() else ""
