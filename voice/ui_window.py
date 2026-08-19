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
its Edge/Chrome subprocess launch.

A second, small always-on-top window (the "mini" popup) is created
alongside the main one -- pywebview runs one GUI loop per process, so
every window has to exist before webview.start() is called. It points at
`/?mini=1`, a stripped-down view of the same orb.html (see that file's
`body.mini` CSS), and is shown/hidden by voice/tts.py while she's
speaking -- but only when the main window isn't already visible (tracked
via _main_visible below), since the full window already shows the same
speaking state and a second indicator would be redundant.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_window = None
_available = False
_main_visible = True  # the main window is shown by default once created

_mini_window = None
_mini_available = False

# The mini window shows a shrunk orb (voice/static/orb.html's body.mini CSS
# hides all HUD chrome and keeps just the orb canvases), so it's square. The
# window is kept opaque near-black -- transparent WebView2 windows clip/offset
# their content inside the WinForms host, so we don't use them.
_MINI_WIDTH = 190
_MINI_HEIGHT = 190
_MINI_MARGIN = 24


def is_available() -> bool:
    """True once the native window has been created successfully."""
    return _available


def show() -> None:
    """Bring the native window to front. No-op if it was never created."""
    global _main_visible
    if _window is not None:
        _window.show()
        _main_visible = True


def start(port: int, token: str) -> None:
    """Create the native window(s) and run pywebview's GUI loop on the
    calling thread -- must be called from the process's real main thread.
    Blocks for the rest of the process's life on success. Returns (without
    blocking) if window creation fails, e.g. no WebView2 runtime -- the
    caller is expected to fall back to voice/ui_server.py's Edge/Chrome
    subprocess launch in that case."""
    global _window, _available, _mini_window, _mini_available
    try:
        window, webview_mod = _create_window(port, token)
    except Exception:
        logger.exception("[ui_window] native window unavailable, falling back to browser launch")
        return
    _window = window
    _available = True

    try:
        _mini_window = _create_mini_window(webview_mod, port, token)
        _mini_available = True
    except Exception:
        logger.exception("[ui_window] mini speaking-popup window unavailable")

    webview_mod.start()


def show_mini() -> None:
    """Show the mini speaking-popup window -- unless the main orb window is
    already visible (it shows the same speaking state), or the popup is
    disabled/unavailable. Config is re-read on every call so toggling
    speaking_popup_enabled in Settings applies without a restart."""
    if not _mini_available or _main_visible:
        return
    from voice import config as cfg
    if not cfg.load().get("speaking_popup_enabled", True):
        return
    try:
        _mini_window.show()
    except Exception:
        pass


def hide_mini() -> None:
    """Hide the mini speaking-popup window. Safe no-op if it was never
    created or is already hidden."""
    if not _mini_available:
        return
    try:
        _mini_window.hide()
    except Exception:
        pass


def reload() -> None:
    """Reload the served page in place -- for settings baked into the HTML
    at request time (e.g. ui_render_mode) that a live WS push can't apply.
    Uses the page's own JS rather than window.load_url() so it doesn't need
    to reconstruct the URL/token. Safe no-op for any window never created."""
    for win in (_window, _mini_window):
        if win is None:
            continue
        try:
            win.evaluate_js("location.reload()")
        except Exception:
            logger.exception("[ui_window] reload failed")


def _on_closing(window) -> bool:
    """Wired to window.events.closing: hide instead of destroy, and cancel
    the actual close (pywebview treats a False return as 'don't close')."""
    global _main_visible
    _main_visible = False
    window.hide()
    return False


def _create_window(port: int, token: str):
    """Import pywebview and create the main window (shown by default once
    the GUI loop starts -- see start()). Split out from start() so tests
    can monkeypatch this one call to simulate success/failure without a
    real WebView2 runtime."""
    import webview

    url = f"http://127.0.0.1:{port}?t={token}"
    window = webview.create_window("Vesper", url, width=900, height=700)
    window.events.closing += lambda: _on_closing(window)
    return window, webview


def _mini_position(width: int, height: int, corner: str) -> tuple[int, int]:
    """Screen-corner coordinates for the mini window, from the Windows
    desktop resolution (win32api -- pywebview's own screen query is only
    populated once the GUI loop is already running, too late for
    create_window()'s x/y arguments)."""
    import win32api
    import win32con
    sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    x = sw - width - _MINI_MARGIN if "right" in corner else _MINI_MARGIN
    if "middle" in corner:
        y = (sh - height) // 2
    else:
        y = sh - height - _MINI_MARGIN if "bottom" in corner else _MINI_MARGIN
    return x, y


def _create_mini_window(webview_mod, port: int, token: str):
    """Create the small always-on-top speaking-popup window, hidden until
    voice/tts.py calls show_mini()."""
    from voice import config as cfg
    corner = cfg.load().get("speaking_popup_corner", "middle-right")
    x, y = _mini_position(_MINI_WIDTH, _MINI_HEIGHT, corner)
    url = f"http://127.0.0.1:{port}/?mini=1&t={token}"
    return webview_mod.create_window(
        "Vesper — speaking", url,
        width=_MINI_WIDTH, height=_MINI_HEIGHT, x=x, y=y,
        frameless=True, on_top=True, hidden=True, easy_drag=False,
        resizable=False, background_color="#0a0a10",
    )
