"""Tests for voice/main.py's screen-read startup gating."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from voice import main


def test_maybe_start_screen_read_noop_when_disabled():
    with patch("voice.screen_overlay.ScreenOverlay") as MockOverlay:
        result = main._maybe_start_screen_read({"screen_read_enabled": False})
    MockOverlay.assert_not_called()
    assert result is None


def test_maybe_start_screen_read_starts_when_enabled():
    with patch("voice.screen_overlay.ScreenOverlay") as MockOverlay, \
         patch("voice.screen_read_hotkeys.ScreenReadHotkeys") as MockHotkeys, \
         patch("threading.Thread") as MockThread:
        mock_overlay_instance = MockOverlay.return_value
        result = main._maybe_start_screen_read({"screen_read_enabled": True})

    mock_overlay_instance.start.assert_called_once()
    MockHotkeys.assert_called_once()
    MockThread.assert_called_once()
    MockThread.return_value.start.assert_called_once()
    assert result is not None  # returns the stop_event for shutdown
