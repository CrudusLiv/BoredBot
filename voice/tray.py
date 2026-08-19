"""Windows system tray — pystray icon + right-click menu + toast notifications.

Phase D. Requires: pip install pystray Pillow plyer
Auto-start shortcut written to Startup folder only when install_autostart() is
called explicitly (not done automatically on every launch).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

_icon = None  # pystray.Icon, set by start()
_port: int = 7070

# So a glance at the taskbar tray answers "is she running / paused / stuck"
# without opening the window: the tray icon's orb color tracks the same
# `state` events the orb UI listens to (voice/ui_server.py::post_event),
# and greys out on killswitch pause. Labels/colors keyed by the `value` of
# {"type": "state", "value": ...} events emitted from voice/main.py and
# voice/brain.py.
_STATE_COLORS: dict[str, tuple] = {
    "idle": ((68, 34, 170, 220), (102, 85, 187, 255)),      # violet -- default
    "listening": ((34, 140, 90, 220), (90, 200, 140, 255)),  # green
    "thinking": ((176, 128, 32, 220), (216, 172, 80, 255)),  # amber
    "speaking": ((32, 110, 176, 220), (80, 160, 216, 255)),  # blue
    "error": ((176, 40, 40, 220), (216, 90, 90, 255)),       # red
}
_STATE_LABELS: dict[str, str] = {
    "idle": "idle", "listening": "listening…", "thinking": "thinking…",
    "speaking": "speaking…", "error": "error",
}
_PAUSED_COLORS = ((90, 90, 90, 200), (130, 130, 130, 220))  # desaturated grey

_current_state = "idle"
_paused = False


def _make_image(fill=(68, 34, 170, 220), outline=(102, 85, 187, 255)):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], outline=(136, 102, 204, 120), width=3)   # lilac ring
    d.ellipse([12, 12, 52, 52], fill=fill, outline=outline, width=1)  # state-colored orb
    d.ellipse([22, 18, 28, 24], fill=(136, 204, 34, 200))               # yellow-green highlight
    return img


def set_state(value: str) -> None:
    """Update the tray orb's color/tooltip for a conversational-state change
    (idle/listening/thinking/speaking/error). Safe no-op before the tray
    starts or for an unrecognized value."""
    global _current_state
    if value not in _STATE_COLORS:
        return
    _current_state = value
    _refresh()


def set_paused(paused: bool) -> None:
    """Update the tray orb to reflect killswitch pause state. Safe no-op
    before the tray starts."""
    global _paused
    _paused = bool(paused)
    _refresh()


def _refresh() -> None:
    if _icon is None:
        return
    try:
        if _paused:
            fill, outline = _PAUSED_COLORS
            title = "Vesper — paused"
        else:
            fill, outline = _STATE_COLORS.get(_current_state, _STATE_COLORS["idle"])
            title = f"Vesper — {_STATE_LABELS.get(_current_state, _current_state)}"
        img = _make_image(fill, outline)
        if img is not None:
            _icon.icon = img
        _icon.title = title
    except Exception:
        pass


def notify(title: str, message: str) -> None:
    """Show a toast. Tries pystray built-in first, then plyer, then silently drops."""
    if _icon is not None:
        try:
            _icon.notify(message, title)
            return
        except Exception:
            pass
    try:
        from plyer import notification  # type: ignore
        notification.notify(title=title, message=message, app_name="Vesper", timeout=6)
    except Exception:
        pass


def install_autostart() -> None:
    """Write a .bat shortcut to the Windows Startup folder."""
    import os
    startup = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )
    if not startup.exists():
        return
    bat = startup / "Vesper.bat"
    bat.write_text("@echo off\nstart \"\" pythonw -m voice\n", encoding="utf-8")


def start(port: int = 7070, on_quit: Callable | None = None) -> None:
    """Start the tray icon. Silent no-op if pystray or Pillow are missing."""
    global _icon, _port
    _port = port

    try:
        import pystray  # type: ignore
    except ImportError:
        return

    img = _make_image()
    if img is None:
        return

    def _open(icon, item):
        # App-mode window (own taskbar entry), not a tab in the default browser.
        try:
            from voice import ui_server
            ui_server.open_window()
        except Exception:
            pass

    def _restart(icon, item):
        # Under the vesper-voice scheduled task the start_voice.ps1 watchdog
        # relaunches us ~5s after exit, so plain exit == restart. On a manual
        # run (no watchdog) this just quits.
        icon.stop()
        if on_quit:
            on_quit()

    def _stop_until_logon(icon, item):
        # The sentinel tells start_voice.ps1 to break its relaunch loop
        # instead of restarting us; the logon trigger starts fresh next login.
        try:
            from voice import config as cfg
            (cfg.get_data_dir() / "stop_voice.flag").touch()
        except OSError:
            pass
        icon.stop()
        if on_quit:
            on_quit()

    def _toggle_pause(icon, item):
        from voice import killswitch
        killswitch.toggle()
        icon.update_menu()

    def _reload_ui(icon, item):
        # In-place reload of the served page -- for settings baked into the
        # HTML at request time (e.g. ui_render_mode) that don't apply live.
        try:
            from voice import ui_window
            ui_window.reload()
        except Exception:
            pass

    def _is_paused(item) -> bool:
        from voice import killswitch
        return killswitch.is_paused()

    menu = pystray.Menu(
        pystray.MenuItem("Open Vesper", _open, default=True),
        # A paused Vesper is fully deaf, so she cannot hear "resume duties" —
        # this item and the orb's pause button are the only ways back.
        pystray.MenuItem("Paused (deaf & mute)", _toggle_pause, checked=_is_paused),
        pystray.MenuItem("Reload UI", _reload_ui),
        pystray.MenuItem("Restart Vesper", _restart),
        pystray.MenuItem("Stop until next logon", _stop_until_logon),
    )
    _icon = pystray.Icon("Vesper", img, "Vesper", menu)

    # Sync the orb color/tooltip to whatever the killswitch already says
    # (e.g. paused from a previous session) instead of waiting for the next
    # state-change event to correct it.
    try:
        from voice import killswitch
        _paused_at_start = killswitch.is_paused()
    except Exception:
        _paused_at_start = False
    set_paused(_paused_at_start)

    def _run():
        try:
            _icon.run_detached()
        except AttributeError:
            # pystray < 0.19 lacks run_detached; wrap in thread so we don't block
            _icon.run()

    threading.Thread(target=_run, daemon=True, name="vesper-tray").start()
