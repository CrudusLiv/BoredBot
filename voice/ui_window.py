"""Native window for the orb UI -- pywebview (WebView2), given the real
process main thread by voice/main.py::run() (pywebview's webview.start()
hard-requires it; there is no bypass for running it off-thread).

The window is created once, shown automatically when webview.start()
initializes the GUI loop, and kept alive for the process lifetime: the
native close button hides it instead of destroying it (see _on_closing),
so voice/ui_server.py's open_window()/ensure_window_open() can just call
show() again rather than recreating a window or a browser subprocess.
(window.show() must never be called before webview.start() has run --
pywebview's Window API methods block on a readiness event that only gets
set once the real GUI loop is initialized, and time out with
WebViewException('Main window failed to start') otherwise.)

If pywebview/WebView2 aren't available, start() returns without blocking,
is_available() stays False forever, and voice/ui_server.py falls back to
its Edge/Chrome subprocess launch."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_window = None
_available = False


def is_available() -> bool:
    """True once the native window has been created successfully."""
    return _available


def show() -> None:
    """Bring the native window to front. No-op if it was never created."""
    if _window is not None:
        _window.show()


def start(port: int, token: str) -> None:
    """Create the native window and run pywebview's GUI loop on the calling
    thread -- must be called from the process's real main thread. Blocks for
    the rest of the process's life on success. Returns (without blocking) if
    window creation fails, e.g. no WebView2 runtime -- the caller is
    expected to fall back to voice/ui_server.py's Edge/Chrome subprocess
    launch in that case."""
    global _window, _available
    try:
        window, webview_mod = _create_window(port, token)
    except Exception:
        logger.exception("[ui_window] native window unavailable, falling back to browser launch")
        return
    _window = window
    _available = True
    webview_mod.start()


def _on_closing(window) -> bool:
    """Wired to window.events.closing: hide instead of destroy, and cancel
    the actual close (pywebview treats a False return as 'don't close')."""
    window.hide()
    return False


def _create_window(port: int, token: str):
    """Import pywebview and create the window (shown by default once the GUI
    loop starts -- see start()). Split out from start() so tests can
    monkeypatch this one call to simulate success/failure without a real
    WebView2 runtime."""
    import webview

    url = f"http://127.0.0.1:{port}?t={token}"
    window = webview.create_window("Vesper", url, width=900, height=700)
    window.events.closing += lambda: _on_closing(window)
    return window, webview
