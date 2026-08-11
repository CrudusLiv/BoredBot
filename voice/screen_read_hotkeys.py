"""Screen-read hotkeys -- capture/ask/copy/dismiss. Polls GetAsyncKeyState
directly (not a hook), the same technique voice/audio.py::is_ptt_down uses,
so it keeps working while a game holds fullscreen-exclusive focus.

Runs as its own daemon thread; screen_read.ask_about_images() blocks this
thread while streaming -- never voice/main.py's PTT/text loop.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Iterator

from voice import config as cfg
from voice.audio import _vk_code


def _is_down(key: str) -> bool:
    import win32api
    return bool(win32api.GetAsyncKeyState(_vk_code(key)) & 0x8000)


def _copy_to_clipboard(text: str) -> None:
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


class ScreenReadHotkeys:
    """Owns the in-memory capture batch and the poll loop.

    overlay: an object with show_batching/show_analyzing/append_text/
        show_error/dismiss methods (voice.screen_overlay.ScreenOverlay in
        production; a mock in tests).
    capture_fn: () -> bytes (voice.screen_capture.capture_active_monitor).
    ask_fn: (list[bytes]) -> Iterator[dict] (voice.screen_read.ask_about_images).
    """

    def __init__(self, overlay, capture_fn: Callable[[], bytes],
                 ask_fn: Callable[[list], Iterator[dict]]) -> None:
        self._overlay = overlay
        self._capture_fn = capture_fn
        self._ask_fn = ask_fn
        self._batch: list[bytes] = []
        self._last_response = ""

    def add_capture(self) -> None:
        try:
            image = self._capture_fn()
        except Exception as exc:
            self._overlay.show_error(str(exc))
            return
        self._batch.append(image)
        self._overlay.show_batching(len(self._batch))

    def submit_ask(self) -> None:
        if not self._batch:
            return
        batch, self._batch = self._batch, []
        self._overlay.show_analyzing()
        text = ""
        try:
            for event in self._ask_fn(batch):
                if event["kind"] == "text":
                    self._overlay.append_text(event["text"])
                    text += event["text"]
                elif event["kind"] == "result":
                    text = event["text"] or text
        except Exception as exc:
            self._overlay.show_error(str(exc))
            return
        self._last_response = text

    def copy_last_response(self) -> None:
        if self._last_response:
            _copy_to_clipboard(self._last_response)

    def dismiss(self) -> None:
        self._overlay.dismiss()

    def run(self, stop_event: threading.Event) -> None:
        """Blocking poll loop -- call this on its own daemon thread."""
        conf = cfg.load()
        bindings = {
            conf.get("screen_read_capture_hotkey", ""): self.add_capture,
            conf.get("screen_read_ask_hotkey", ""): self.submit_ask,
            conf.get("screen_read_copy_hotkey", ""): self.copy_last_response,
            conf.get("screen_read_dismiss_hotkey", ""): self.dismiss,
        }
        bindings.pop("", None)  # unset hotkeys are no-ops, never polled
        was_down = {key: False for key in bindings}

        while not stop_event.is_set():
            for key, action in bindings.items():
                down = _is_down(key)
                if down and not was_down[key]:
                    threading.Thread(target=action, daemon=True).start()
                was_down[key] = down
            time.sleep(0.05)
