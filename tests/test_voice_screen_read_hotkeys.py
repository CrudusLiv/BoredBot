"""Tests for voice/screen_read_hotkeys.py::ScreenReadHotkeys. The hotkey
poll loop itself (run()) is not exercised here -- GetAsyncKeyState is a
raw OS poll with no meaningful behavior to unit test, consistent with how
voice/audio.py::is_ptt_down is only exercised indirectly elsewhere. This
file tests the batch-management methods run() calls into."""
from __future__ import annotations

from unittest.mock import MagicMock

from voice.screen_read_hotkeys import ScreenReadHotkeys


def _hotkeys(ask_events=None):
    overlay = MagicMock()
    capture_fn = MagicMock(return_value=b"fakepng")
    ask_fn = MagicMock(return_value=iter(ask_events or []))
    return ScreenReadHotkeys(overlay, capture_fn, ask_fn), overlay, capture_fn, ask_fn


def test_add_capture_appends_to_batch_and_updates_overlay():
    hk, overlay, capture_fn, _ = _hotkeys()
    hk.add_capture()
    capture_fn.assert_called_once()
    overlay.show_batching.assert_called_once_with(1)


def test_add_capture_failure_shows_error_without_growing_batch():
    overlay = MagicMock()
    capture_fn = MagicMock(side_effect=RuntimeError("no monitor"))
    hk = ScreenReadHotkeys(overlay, capture_fn, MagicMock())
    hk.add_capture()
    overlay.show_error.assert_called_once()
    assert hk._batch == []


def test_submit_ask_on_empty_batch_is_noop():
    hk, overlay, _, ask_fn = _hotkeys()
    hk.submit_ask()
    ask_fn.assert_not_called()
    overlay.show_analyzing.assert_not_called()


def test_submit_ask_streams_text_and_clears_batch():
    events = [{"kind": "text", "text": "Hel"}, {"kind": "text", "text": "lo"},
              {"kind": "result", "text": "Hello"}]
    hk, overlay, capture_fn, ask_fn = _hotkeys(events)
    hk.add_capture()
    hk.submit_ask()

    overlay.show_analyzing.assert_called_once()
    overlay.append_text.assert_any_call("Hel")
    overlay.append_text.assert_any_call("lo")
    assert hk._batch == []
    assert hk._last_response == "Hello"


def test_submit_ask_failure_shows_error_and_clears_batch():
    def _raise(images):
        raise RuntimeError("vision call failed")
        yield  # pragma: no cover -- makes this a generator function
    overlay = MagicMock()
    hk = ScreenReadHotkeys(overlay, MagicMock(return_value=b"fakepng"), _raise)
    hk.add_capture()
    hk.submit_ask()
    overlay.show_error.assert_called_once()
    assert hk._batch == []


def test_copy_last_response_copies_when_present(monkeypatch):
    hk, overlay, _, _ = _hotkeys()
    hk._last_response = "some text"
    copied = {}
    monkeypatch.setattr(
        "voice.screen_read_hotkeys._copy_to_clipboard",
        lambda text: copied.setdefault("text", text),
    )
    hk.copy_last_response()
    assert copied["text"] == "some text"


def test_copy_last_response_noop_when_empty(monkeypatch):
    hk, overlay, _, _ = _hotkeys()
    called = []
    monkeypatch.setattr("voice.screen_read_hotkeys._copy_to_clipboard", lambda text: called.append(text))
    hk.copy_last_response()
    assert called == []


def test_dismiss_calls_overlay_dismiss():
    hk, overlay, _, _ = _hotkeys()
    hk.dismiss()
    overlay.dismiss.assert_called_once()
