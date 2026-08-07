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


def _make_image():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], outline=(136, 102, 204, 120), width=3)   # lilac ring
    d.ellipse([12, 12, 52, 52], fill=(68, 34, 170, 220), outline=(102, 85, 187, 255), width=1)  # violet orb
    d.ellipse([22, 18, 28, 24], fill=(136, 204, 34, 200))               # yellow-green highlight
    return img


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
    bat.write_text("@echo off\nstart \"\" pythonw -m voice --voice\n", encoding="utf-8")


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

    menu = pystray.Menu(
        pystray.MenuItem("Open Vesper", _open, default=True),
        pystray.MenuItem("Restart Vesper", _restart),
        pystray.MenuItem("Stop until next logon", _stop_until_logon),
    )
    _icon = pystray.Icon("Vesper", img, "Vesper", menu)

    def _run():
        try:
            _icon.run_detached()
        except AttributeError:
            # pystray < 0.19 lacks run_detached; wrap in thread so we don't block
            _icon.run()

    threading.Thread(target=_run, daemon=True, name="vesper-tray").start()
