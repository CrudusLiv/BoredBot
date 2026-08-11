"""Tests for voice/screen_overlay.py's pure state machine. Tk/win32 window
creation is intentionally not exercised here -- see Task 4 Step 6 for the
manual verification that covers that part."""
from __future__ import annotations

from voice.screen_overlay import _OverlayState


def test_initial_state_is_hidden():
    state = _OverlayState()
    assert state.visible is False
    assert state.text == ""


def test_batching_shows_count():
    state = _OverlayState()
    state.batching(3)
    assert state.visible is True
    assert "3" in state.text


def test_analyzing_shows_thinking():
    state = _OverlayState()
    state.analyzing()
    assert state.visible is True
    assert state.text == "Thinking..."


def test_append_after_analyzing_replaces_thinking_placeholder():
    state = _OverlayState()
    state.analyzing()
    state.append("Hello")
    assert state.text == "Hello"


def test_append_accumulates_chunks():
    state = _OverlayState()
    state.analyzing()
    state.append("Hel")
    state.append("lo")
    assert state.text == "Hello"


def test_error_sets_visible_and_message():
    state = _OverlayState()
    state.error("capture failed")
    assert state.visible is True
    assert "capture failed" in state.text


def test_dismiss_hides_and_clears_text():
    state = _OverlayState()
    state.analyzing()
    state.append("some response")
    state.dismiss()
    assert state.visible is False
    assert state.text == ""
