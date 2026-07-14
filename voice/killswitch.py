"""Global pause switch — halts all proactive/consequential behavior at once.

Paused = a marker file exists at get_data_dir()/killswitch.paused, so the
state survives restarts with zero config-merge complexity. While paused:
  - the wake-word thread stops detecting and the microphone is never opened
  - nothing is spoken, proactive or conversational
  - heartbeat skips ticks and scheduled briefings/nudges
  - confirmation-gated tools are auto-denied

Paused means fully deaf and mute, so the `resume duties` phrase cannot be heard.
Resume from the orb's pause button or the tray's Paused item. voice/silence.py
is the predicate every mic and speaker path actually checks; it ORs this state
together with the heartbeat's busy (silence_when_running) state.
"""
from __future__ import annotations


def _marker():
    from voice import config as cfg
    return cfg.get_data_dir() / "killswitch.paused"


def is_paused() -> bool:
    try:
        return _marker().exists()
    except Exception:
        return False


def set_paused(paused: bool) -> bool:
    """Set the pause state, broadcast it to the UI, and return the new state."""
    try:
        marker = _marker()
        if paused:
            marker.touch(exist_ok=True)
        else:
            marker.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[killswitch] failed to set paused={paused}: {exc}", flush=True)
    _broadcast()
    return is_paused()


def toggle() -> bool:
    return set_paused(not is_paused())


def _broadcast() -> None:
    try:
        from voice import ui_server
        ui_server.post_event({"type": "killswitch", "paused": is_paused()})
    except Exception:
        pass
