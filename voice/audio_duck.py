"""System audio ducking while Vesper speaks -- lowers every other process's
Windows audio session volume via pycaw, restores it exactly afterward.

Opt-in (config `audio_duck_enabled`); silently no-ops if pycaw isn't
installed or ducking is off, matching this codebase's fallback pattern for
optional Windows integrations (see voice/tray.py's pystray check).
"""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
# pid -> (SimpleAudioVolume COM wrapper, original volume 0.0-1.0)
_ducked: dict[int, tuple[object, float]] = {}


def _com_init() -> None:
    """COM must be initialized on whatever thread touches pycaw's COM
    objects -- duck()/restore() run on voice/tts.py's playback threads, not
    the process's main thread (which is where most COM libraries assume
    initialization already happened). Safe to call repeatedly on the same
    thread: a thread that's already STA-initialized just gets S_FALSE back,
    not an exception."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass


def duck() -> None:
    """Scale every other process's audio session volume down to
    audio_duck_percent of its current level. Idempotent: a second call
    while already ducked is a no-op, since a streamed utterance calls this
    once per sentence but should only actually duck once."""
    from voice import config as cfg
    conf = cfg.load()
    if not conf.get("audio_duck_enabled", False):
        return

    with _lock:
        if _ducked:
            return  # already ducked -- restore() hasn't run yet

        try:
            from pycaw.pycaw import AudioUtilities
        except ImportError:
            return
        _com_init()

        ratio = max(0.0, min(1.0, conf.get("audio_duck_percent", 25) / 100.0))
        own_pid = os.getpid()

        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception:
            return

        for session in sessions:
            proc = getattr(session, "Process", None)
            if proc is None or proc.pid == own_pid:
                continue
            try:
                volume = session.SimpleAudioVolume
                original = volume.GetMasterVolume()
                volume.SetMasterVolume(original * ratio, None)
                _ducked[proc.pid] = (volume, original)
            except Exception:
                continue


def restore() -> None:
    """Put every ducked session's volume back exactly. Best-effort -- a
    session whose process closed while ducked is just skipped."""
    with _lock:
        if not _ducked:
            return
        _com_init()
        for volume, original in _ducked.values():
            try:
                volume.SetMasterVolume(original, None)
            except Exception:
                pass
        _ducked.clear()
