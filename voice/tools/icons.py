"""App icon resolution + extraction for the Config tab's PC-control and
activity-awareness lists. resolve_exe_path() maps a saved target (a full exe
path, a bare exe name, or a URI) to a real .exe on disk; extract_icon_png()
and get_icon_png() (added in later tasks) turn that into cached PNG bytes."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path


def resolve_exe_path(target: str) -> str | None:
    """Resolve a PC-control target or an activity-awareness exe name to a
    real, existing .exe path, or None if it can't be resolved: a non-exe
    path/URI (e.g. "spotify:"), a missing file, or a bare name matched by
    none of the lookups below.

    A bare name (most activity-awareness entries -- "game.exe" typed by hand,
    not picked from the PC-control autocomplete) tries, in order: the Start
    Menu shortcut scan, the Windows "App Paths" registry, PATH, then the
    currently-running process list. Many exes -- games launched via a
    launcher, background/helper processes -- have no Start Menu shortcut at
    all, which is why some activity-awareness entries showed no icon while
    every PC-control one (always shortcut- or hand-path-backed) did."""
    target = (target or "").strip()
    if not target:
        return None
    has_sep = "\\" in target or "/" in target
    if has_sep:
        if not target.lower().endswith(".exe"):
            return None
        p = Path(target)
        return str(p) if p.is_file() else None
    name = target.lower()
    if not name.endswith(".exe"):
        name += ".exe"
    from voice.tools import pc_control
    for app in pc_control.discover_apps():
        app_target = app.get("target", "")
        if Path(app_target).name.lower() == name:
            return app_target
    found = _app_paths_registry(name)
    if found:
        return found
    found = _on_path(name)
    if found:
        return found
    found = _running_process(name)
    if found:
        return found
    return None


def _app_paths_registry(name: str) -> str | None:
    """Look up name in the Windows "App Paths" registry key, which many
    installers populate independently of a Start Menu shortcut. Checks
    HKCU before HKLM (matches shell resolution order). Fails closed (None)
    on any error, including not running on Windows."""
    try:
        import winreg
    except ImportError:
        return None
    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + name
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value and Path(value).is_file():
                    return value
        except OSError:
            continue
    return None


def _on_path(name: str) -> str | None:
    """Look up name on PATH via shutil.which."""
    import shutil
    return shutil.which(name)


def _running_process(name: str) -> str | None:
    """Find name among currently-running processes and return its exe path.
    Lazy psutil import, fail-open -- same contract as
    voice/activity.py::running_processes()."""
    try:
        import psutil
    except Exception:
        return None
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                if (proc.info.get("name") or "").lower() == name:
                    exe = proc.info.get("exe")
                    if exe and Path(exe).is_file():
                        return exe
            except Exception:
                continue
    except Exception:
        return None
    return None


def extract_icon_png(exe_path: str) -> bytes | None:
    """Extract the exe's first icon resource and return it PNG-encoded, or
    None if it has no icon or extraction fails for any reason (corrupt exe,
    no icon resource, GDI failure)."""
    import win32gui

    large, small = win32gui.ExtractIconEx(exe_path, 0)
    handles = list(large or []) + list(small or [])
    if not handles:
        return None
    try:
        return _render_icon_png(handles[0])
    except Exception:
        return None
    finally:
        for h in handles:
            win32gui.DestroyIcon(h)


def _render_icon_png(hicon, size: int = 32) -> bytes:
    """GDI-render a single HICON into a size x size PNG via a memory device
    context, using PIL to encode the resulting BGRA bitmap."""
    import win32con
    import win32gui
    import win32ui
    from PIL import Image

    hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
    hdc_mem = hdc.CreateCompatibleDC()
    hbmp = win32ui.CreateBitmap()
    hbmp.CreateCompatibleBitmap(hdc, size, size)
    hdc_mem.SelectObject(hbmp)
    try:
        win32gui.DrawIconEx(hdc_mem.GetHandleOutput(), 0, 0, hicon, size, size, 0, None, win32con.DI_NORMAL)
        info = hbmp.GetInfo()
        bits = hbmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGBA", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRA", 0, 1
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        win32gui.DeleteObject(hbmp.GetHandle())
        hdc_mem.DeleteDC()
        hdc.DeleteDC()


def _cache_dir() -> Path:
    from voice import config as cfg
    d = cfg.get_data_dir() / "icon_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_icon_png(target: str) -> bytes | None:
    """Resolve target to an exe path, extract+disk-cache its icon (icons
    never change, so the cache never expires), and return PNG bytes -- or
    None if target can't be resolved or has no icon."""
    exe_path = resolve_exe_path(target)
    if exe_path is None:
        return None
    key = hashlib.sha1(exe_path.lower().encode("utf-8")).hexdigest()
    cache_file = _cache_dir() / f"{key}.png"
    if cache_file.exists():
        return cache_file.read_bytes()
    png = extract_icon_png(exe_path)
    if png is None:
        return None
    cache_file.write_bytes(png)
    return png
