"""Tests for the global silence gate.

Two independent sources — the killswitch marker and the heartbeat's busy state —
must both make Vesper fully deaf and mute: no mic, no speech. Covers the gate
itself and the TTS entry points.
"""
from __future__ import annotations

import threading

import pytest

from voice import config as cfg
from voice import silence


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Fresh data dir (so the real killswitch marker never leaks in) and a
    busy flag reset around every test — both are process-global."""
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    silence.set_busy(False)
    yield
    silence.set_busy(False)


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def test_not_silenced_by_default():
    assert silence.is_silenced() is False
    assert silence.reason() == ""


def test_killswitch_silences():
    from voice import killswitch
    killswitch.set_paused(True)
    assert silence.is_silenced() is True
    assert silence.reason() == "paused"


def test_busy_process_silences():
    silence.set_busy(True)
    assert silence.is_silenced() is True
    assert silence.reason() == "busy"


def test_killswitch_outranks_busy_in_reason():
    from voice import killswitch
    killswitch.set_paused(True)
    silence.set_busy(True)
    assert silence.reason() == "paused"


def test_resume_clears_killswitch():
    from voice import killswitch
    killswitch.set_paused(True)
    killswitch.set_paused(False)
    assert silence.is_silenced() is False


# --------------------------------------------------------------------------
# TTS is gated — nothing speaks while silenced
# --------------------------------------------------------------------------

def test_speak_drops_while_silenced(monkeypatch):
    from voice import tts
    played: list[str] = []
    monkeypatch.setattr(tts, "_play", lambda text, on_done=None: played.append(text))
    silence.set_busy(True)

    done = threading.Event()
    tts.speak("should not be heard", on_done=done.set)

    assert played == []
    # on_done MUST still fire: callers depend on it to release whatever
    # they're waiting on. Dropping it silently deadlocks the caller.
    assert done.is_set()


def test_speak_plays_when_not_silenced(monkeypatch):
    from voice import tts
    played: list[str] = []
    monkeypatch.setattr(tts, "_play", lambda text, on_done=None: played.append(text))
    tts.speak("audible")
    for _ in range(200):
        if played:
            break
        threading.Event().wait(0.01)
    assert played == ["audible"]


def test_begin_utterance_is_inert_while_silenced():
    from voice import tts
    silence.set_busy(True)
    done = threading.Event()
    utt = tts.begin_utterance(on_done=done.set)
    utt.feed("nothing")
    utt.close()
    assert done.is_set()


# --------------------------------------------------------------------------
# Proactive speaker thread honours the gate (not just the killswitch)
# --------------------------------------------------------------------------

def test_proactive_speaker_holds_while_busy(monkeypatch):
    import queue
    from voice import main as main_mod, tts

    spoken: list[str] = []
    monkeypatch.setattr(tts, "speak", lambda text, on_done=None: spoken.append(text))
    monkeypatch.setattr(cfg, "is_quiet_hours", lambda: False)

    silence.set_busy(True)
    q: "queue.Queue[str]" = queue.Queue()
    stop = threading.Event()
    main_mod._start_proactive_speaker(q, stop)
    q.put("held line")
    threading.Event().wait(0.3)
    stop.set()

    assert spoken == []
