"""Tests for voice/screen_read_hotkeys.py::ScreenReadHotkeys. Most of this
file tests the batch-management methods run() calls into -- the raw
GetAsyncKeyState poll itself has no meaningful behavior to unit test,
consistent with how voice/audio.py::is_ptt_down is only exercised
indirectly elsewhere. One test does exercise run() directly: it must
reload config on each poll tick rather than snapshotting it once, so a
hotkey changed via the Config UI takes effect without restarting Vesper."""
from __future__ import annotations

import threading
import time
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


def test_run_picks_up_hotkey_change_without_restart(monkeypatch):
    """A hotkey changed via the Config UI (which just rewrites config.json)
    must take effect on the poll loop's next tick -- not require restarting
    Vesper. Regression test for run() snapshotting config once outside the
    loop instead of reloading it each tick."""
    hk, overlay, capture_fn, _ = _hotkeys()

    configs = [{"screen_read_capture_hotkey": "f9"}, {"screen_read_capture_hotkey": "f6"}]
    calls = {"n": 0}

    def fake_load():
        idx = min(calls["n"], len(configs) - 1)
        calls["n"] += 1
        return configs[idx]

    monkeypatch.setattr("voice.screen_read_hotkeys.cfg.load", fake_load)
    monkeypatch.setattr("voice.screen_read_hotkeys._is_down", lambda key: key == "f6")
    monkeypatch.setattr("voice.screen_read_hotkeys.time.sleep", lambda _s: None)

    stop_event = threading.Event()

    def _stop_after_a_few_ticks():
        while calls["n"] < 5:
            time.sleep(0.01)
        stop_event.set()

    threading.Thread(target=_stop_after_a_few_ticks, daemon=True).start()
    hk.run(stop_event)

    for _ in range(200):
        if capture_fn.called:
            break
        time.sleep(0.01)
    capture_fn.assert_called()
