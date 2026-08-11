"""Native window for the orb UI -- pywebview (WebView2) on its own thread.

Runs on a dedicated thread with its own GUI loop, the same shape
voice/screen_overlay.py uses for the screen-read overlay. The window is
created once, hidden, and kept alive for the process lifetime: the native
close button hides it instead of destroying it (see _on_closing), so
voice/ui_server.py's start()/open_window()/ensure_window_open() can just
call show() again rather than recreating a window or a browser subprocess.

If pywebview/WebView2 aren't available, is_available() stays False forever
and voice/ui_server.py falls back to its Edge/Chrome subprocess launch."""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_window = None
_available = False
_ready = threading.Event()


def is_available() -> bool:
    """True once the native window has been created successfully."""
    return _available


def show() -> None:
    """Bring the native window to front. No-op if it was never created."""
    if _window is not None:
        _window.show()


def start(port: int, token: str) -> None:
    """Disabled for now: pywebview's webview.start() hard-requires the
    process's real main thread (unconditional check in
    webview/__init__.py -- no bypass), which a dedicated background
    thread can never satisfy. voice/ui_server.py calls this
    unconditionally; leaving is_available() permanently False here means
    it transparently falls back to _open_app_window() (Edge/Chrome
    subprocess), i.e. today's known-working behavior, until
    voice/main.py is restructured to give pywebview the main thread and
    move its own interactive loop to a background thread instead."""
    return


def _on_closing(window) -> bool:
    """Wired to window.events.closing: hide instead of destroy, and cancel
    the actual close (pywebview treats a False return as 'don't close')."""
    window.hide()
    return False


def _create_window(port: int, token: str):
    """Import pywebview and create the hidden window. Split out from _run()
    so tests can monkeypatch this one call to simulate success/failure
    without a real WebView2 runtime."""
    import webview

    url = f"http://127.0.0.1:{port}?t={token}"
    window = webview.create_window("Vesper", url, width=900, height=700, hidden=True)
    window.events.closing += lambda: _on_closing(window)
    return window, webview


def _run(port: int, token: str) -> None:
    global _window, _available
    try:
        window, webview_mod = _create_window(port, token)
    except Exception:
        logger.exception("[ui_window] native window unavailable, falling back to browser launch")
        _ready.set()
        return
    _window = window
    _available = True
    _ready.set()
    webview_mod.start()
