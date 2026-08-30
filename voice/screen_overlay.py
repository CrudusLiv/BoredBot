"""Overlay window for screen-read responses -- never steals focus, never
becomes the active window. A customtkinter Toplevel (customtkinter is
already a project dependency, used by voice/setup_wizard.py) is patched
post-creation with WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW so it survives
full-screen exclusive games without stealing focus.

Runs on its own thread with its own mainloop(); all cross-thread updates
go through a thread-safe queue drained via .after() polling -- the same
bridging shape voice/ui_server.py already uses to get its asyncio loop's
events out to WebSocket clients.
"""
from __future__ import annotations

import queue
import threading

_WIDTH = 420
_HEIGHT = 220
_MARGIN = 24
_AUTO_FADE_MS = 30_000
_POLL_MS = 50

_HEIGHT_CAP_FRAC = 0.70
_LINE_PX = 20
_CHARS_PER_LINE = 50
_CHROME_PX = 32


def _wrapped_lines(text: str, width: int = _CHARS_PER_LINE) -> list[str]:
    """Estimate the display lines `text` occupies once word-wrapped in the
    label. Explicit newlines always break; long runs split every `width`
    chars. An approximation -- exact metrics need a live Tk font, and this
    only has to size a glanceable overlay."""
    out: list[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            out.append("")
            continue
        for i in range(0, len(paragraph), width):
            out.append(paragraph[i:i + width])
    return out or [""]


def _fit_geometry(text: str, screen_h: int) -> tuple[int, int, str]:
    """Grow the window upward to fit `text`, capped at `_HEIGHT_CAP_FRAC` of
    the screen. Returns (height, y, shown): height clamped to
    [_HEIGHT, cap], y placing the bottom edge at the corner margin, and
    shown trimmed to the newest lines (prefixed '…') when the full text
    would overflow the cap."""
    cap = int(screen_h * _HEIGHT_CAP_FRAC)
    lines = _wrapped_lines(text)
    needed = len(lines) * _LINE_PX + _CHROME_PX
    height = min(max(needed, _HEIGHT), cap)
    capacity = max((height - _CHROME_PX) // _LINE_PX, 1)
    if len(lines) > capacity:
        keep = max(capacity - 1, 1)
        shown = "…\n" + "\n".join(lines[-keep:])
    else:
        shown = text
    y = screen_h - height - _MARGIN
    return height, y, shown


class _OverlayState:
    """Pure hidden -> batching -> analyzing -> showing -> dismissed state
    machine. No Tk/win32 dependency -- testable headless."""

    def __init__(self) -> None:
        self.visible = False
        self.text = ""

    def batching(self, count: int) -> None:
        self.text = f"[{count} captured] Press ask to analyze."
        self.visible = True

    def analyzing(self) -> None:
        self.text = "Thinking..."
        self.visible = True

    def append(self, chunk: str) -> None:
        if self.text == "Thinking...":
            self.text = ""
        self.text += chunk
        self.visible = True

    def error(self, message: str) -> None:
        self.text = f"Screen-read error: {message}"
        self.visible = True

    def dismiss(self) -> None:
        self.visible = False
        self.text = ""


class ScreenOverlay:
    """Owns the overlay window's lifecycle on a dedicated thread. All
    public methods are safe to call from any thread -- they just push onto
    an internal queue the Tk thread drains."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="vesper-screen-overlay").start()
        self._ready.wait(timeout=5.0)

    def show_batching(self, count: int) -> None:
        self._queue.put(("batching", count))

    def show_analyzing(self) -> None:
        self._queue.put(("analyzing", None))

    def append_text(self, chunk: str) -> None:
        self._queue.put(("append", chunk))

    def show_error(self, message: str) -> None:
        self._queue.put(("error", message))

    def dismiss(self) -> None:
        self._queue.put(("dismiss", None))

    def _run(self) -> None:
        import customtkinter as ctk

        app = ctk.CTk()
        app.overrideredirect(True)
        app.attributes("-topmost", True)
        app.attributes("-alpha", 0.92)
        app.geometry(self._corner_geometry(app))
        app.withdraw()

        label = ctk.CTkLabel(app, text="", justify="left", wraplength=_WIDTH - 32, anchor="nw")
        label.pack(fill="both", expand=True, padx=16, pady=16)

        self._apply_noactivate_style(app)

        state = _OverlayState()
        fade_job = {"id": None}
        x = app.winfo_screenwidth() - _WIDTH - _MARGIN

        def _cancel_fade() -> None:
            if fade_job["id"] is not None:
                app.after_cancel(fade_job["id"])
                fade_job["id"] = None

        def _schedule_fade() -> None:
            _cancel_fade()
            fade_job["id"] = app.after(_AUTO_FADE_MS, state.dismiss)

        def _sync() -> None:
            height, y, shown = _fit_geometry(state.text, app.winfo_screenheight())
            label.configure(text=shown)
            app.geometry(f"{_WIDTH}x{height}+{x}+{y}")
            if state.visible:
                app.deiconify()
            else:
                app.withdraw()

        def _poll() -> None:
            try:
                while True:
                    kind, payload = self._queue.get_nowait()
                    if kind == "batching":
                        state.batching(payload)
                        _cancel_fade()
                    elif kind == "analyzing":
                        state.analyzing()
                        _cancel_fade()
                    elif kind == "append":
                        state.append(payload)
                    elif kind == "error":
                        state.error(payload)
                        _schedule_fade()
                    elif kind == "dismiss":
                        state.dismiss()
                        _cancel_fade()
                    _sync()
            except queue.Empty:
                pass
            app.after(_POLL_MS, _poll)

        app.after(_POLL_MS, _poll)
        self._ready.set()
        app.mainloop()

    @staticmethod
    def _corner_geometry(app) -> str:
        sw = app.winfo_screenwidth()
        sh = app.winfo_screenheight()
        x = sw - _WIDTH - _MARGIN
        y = sh - _HEIGHT - _MARGIN
        return f"{_WIDTH}x{_HEIGHT}+{x}+{y}"

    @staticmethod
    def _apply_noactivate_style(app) -> None:
        import win32con
        import win32gui

        hwnd = app.winfo_id()
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd, win32con.GWL_EXSTYLE,
            style | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW,
        )
