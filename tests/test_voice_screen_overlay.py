"""Tests for voice/screen_overlay.py's pure state machine. Tk/win32 window
creation is intentionally not exercised here -- see Task 4 Step 6 for the
manual verification that covers that part."""
from __future__ import annotations

from voice.screen_overlay import _HEIGHT, _MARGIN, _fit_geometry, _OverlayState


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


SCREEN_H = 1080


def test_fit_geometry_short_text_uses_min_height():
    height, y, shown = _fit_geometry("Just a line.", SCREEN_H)
    assert height == _HEIGHT
    assert shown == "Just a line."


def test_fit_geometry_grows_upward_to_fit_medium_text():
    text = "\n".join(f"line {i}" for i in range(15))
    height, y, shown = _fit_geometry(text, SCREEN_H)
    assert _HEIGHT < height < int(SCREEN_H * 0.70)
    assert shown == text  # nothing trimmed


def test_fit_geometry_caps_height_and_trims_to_newest_text():
    text = "\n".join(f"line {i}" for i in range(400))
    height, y, shown = _fit_geometry(text, SCREEN_H)
    assert height == int(SCREEN_H * 0.70)
    assert shown.startswith("…")
    assert "line 399" in shown  # tail kept
    assert "line 0" not in shown  # head dropped


def test_fit_geometry_pins_bottom_edge_to_corner_margin():
    for text in ("short", "\n".join("x" * 80 for _ in range(200))):
        height, y, _ = _fit_geometry(text, SCREEN_H)
        assert y + height == SCREEN_H - _MARGIN


def test_fit_geometry_never_exceeds_height_cap():
    text = "word " * 5000
    height, _, _ = _fit_geometry(text, SCREEN_H)
    assert height <= int(SCREEN_H * 0.70)
