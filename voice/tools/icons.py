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
    path/URI (e.g. "spotify:"), a missing file, or a bare name with no
    matching Start Menu shortcut."""
    target = (target or "").strip()
    if not target:
        return None
    has_sep = "\\" in target or "/" in target
    if has_sep:
        if not target.lower().endswith(".exe"):
            return None
        p = Path(target)
        return str(p) if p.is_file() else None
    # bare name (e.g. "zoom.exe" or "zoom") -- match against the Start Menu scan
    from voice.tools import pc_control
    name = target.lower()
    if not name.endswith(".exe"):
        name += ".exe"
    for app in pc_control.discover_apps():
        app_target = app.get("target", "")
        if Path(app_target).name.lower() == name:
            return app_target
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
