"""Active-monitor screenshot via windows-capture (Windows.Graphics.Capture).

Unlike mss/PIL.ImageGrab (GDI BitBlt), WGC can capture a fullscreen-
exclusive app (e.g. a game) without kicking it out of exclusive mode --
that's the whole reason this dependency exists instead of a GDI-based one.
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path

_CAPTURE_TIMEOUT_S = 5.0


def _active_monitor_index() -> int:
    """1-based index matching windows-capture's monitor_index, aligned to
    win32api.EnumDisplayMonitors()'s enumeration order."""
    import win32api
    import win32gui

    hwnd = win32gui.GetForegroundWindow()
    active_hmonitor = win32api.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    monitors = win32api.EnumDisplayMonitors()
    for i, entry in enumerate(monitors, start=1):
        if entry[0] == active_hmonitor:
            return i
    return 1  # fail open to the primary monitor if no match found


def capture_active_monitor() -> bytes:
    """Screenshot the monitor that currently has focus. Raises RuntimeError
    if windows-capture/pywin32 aren't installed, or capture doesn't
    complete within _CAPTURE_TIMEOUT_S seconds."""
    try:
        from windows_capture import WindowsCapture
    except ImportError as exc:
        raise RuntimeError(
            f"Screen-read requires extra deps: pip install windows-capture  ({exc})"
        ) from exc

    monitor_index = _active_monitor_index()
    tmp_path = Path(tempfile.gettempdir()) / f"vesper_screen_{threading.get_ident()}.png"
    done = threading.Event()

    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        monitor_index=monitor_index,
        window_name=None,
    )

    @capture.event
    def on_frame_arrived(frame, capture_control):
        frame.save_as_image(str(tmp_path))
        capture_control.stop()
        done.set()

    @capture.event
    def on_closed():
        done.set()

    capture.start()
    if not done.wait(timeout=_CAPTURE_TIMEOUT_S):
        raise RuntimeError("screen capture timed out")
    try:
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)
