"""PC control tools: media playback, system volume, app launching, window
focus. Windows-only. launch_app (Task 3) is allowlist-only -- everything
else here is reversible/low-risk and needs no confirmation gate."""
from __future__ import annotations

import voice  # noqa: F401

# Windows virtual-key codes for media/volume keys (distinct from the
# _NAMED_VK table in voice/audio.py, which covers PTT key names only).
_MEDIA_VK: dict[str, int] = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "prev": 0xB1,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}

_LABELS: dict[str, str] = {
    "play_pause": "toggled play/pause",
    "next": "skipped to next track",
    "prev": "went back a track",
    "volume_up": "turned volume up",
    "volume_down": "turned volume down",
    "mute": "toggled mute",
}


def media_control(action: str) -> str:
    """Simulate a media key press. Args: action — one of play_pause, next,
    prev, volume_up, volume_down, mute."""
    vk = _MEDIA_VK.get(action)
    if vk is None:
        return f"unknown media action: {action!r}. Valid: {', '.join(_MEDIA_VK)}"
    import win32api
    import win32con
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    return _LABELS[action]


def _volume_endpoint():
    """Return the Windows Core Audio master-volume interface for the
    default output device. Split out so tests can patch it directly
    without needing a real audio device or COM initialisation."""
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(level: int) -> str:
    """Set system output volume to an absolute percentage (0-100),
    clamped to that range. Args: level(int)."""
    clamped = max(0, min(100, int(level)))
    endpoint = _volume_endpoint()
    endpoint.SetMasterVolumeLevelScalar(clamped / 100.0, None)
    return f"volume set to {clamped}%"


def launch_app(name: str) -> str:
    """Launch a configured application by spoken name. Allowlist-only —
    only names present in voice/config.json's pc_control_apps may be
    launched; anything else is refused, not attempted. Args: name(str)."""
    from voice import config as cfg
    apps = cfg.load().get("pc_control_apps", {}) or {}
    lookup = {k.lower(): v for k, v in apps.items()}
    target = lookup.get(name.lower())
    if target is None:
        allowed = ", ".join(sorted(apps)) or "(none configured)"
        return f"{name!r} is not allowed. Configured apps: {allowed}"
    import os
    try:
        os.startfile(target)  # nosec B606 -- target is allowlist-resolved, not raw voice input
    except OSError as exc:
        return f"failed to launch {name!r}: {exc}"
    return f"launched {name}"


def _visible_windows() -> list[tuple[int, str]]:
    """Return (hwnd, title) for every visible top-level window with a
    non-empty title."""
    import win32gui
    found: list[tuple[int, str]] = []

    def _collect(hwnd, _extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                found.append((hwnd, title))

    win32gui.EnumWindows(_collect, None)
    return found


def list_windows() -> str:
    """List visible top-level window titles, one per line."""
    windows = _visible_windows()
    if not windows:
        return "no visible windows found"
    return "\n".join(title for _hwnd, title in windows)


def focus_window(name: str) -> str:
    """Bring the first visible window whose title contains `name`
    (case-insensitive) to the foreground. Note: Windows restricts which
    processes may steal foreground focus from the user's active window --
    this may only flash the taskbar icon rather than fully focus, depending
    on OS state. Args: name(str)."""
    needle = name.lower()
    for hwnd, title in _visible_windows():
        if needle in title.lower():
            import win32con
            import win32gui
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return f"focused {title!r}"
    return f"no window found matching {name!r}"


def _start_menu_dirs() -> list:
    """Start Menu Programs folders to scan for shortcuts: the current
    user's and the all-users one. Split out so tests can point this at a
    temp directory instead of the real Start Menu."""
    import os
    from pathlib import Path
    return [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]


def _resolve_shortcut(path) -> str:
    """Return the target path a .lnk shortcut points to, or "" if it can't
    be resolved. Split out so tests can mock the COM call directly."""
    import win32com.client
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        return shell.CreateShortcut(str(path)).Targetpath or ""
    except Exception:
        return ""


def discover_apps() -> list[dict[str, str]]:
    """Scan Start Menu shortcuts (current user + all users) and resolve
    each .lnk to its target .exe. Used by the settings UI to autocomplete
    pc_control_apps entries instead of requiring hand-typed paths. Deduped
    by shortcut name (case-insensitive), sorted by name. Returns
    [{"name": str, "target": str}, ...]."""
    found: dict[str, str] = {}
    for base in _start_menu_dirs():
        if not base.is_dir():
            continue
        for lnk in base.rglob("*.lnk"):
            target = _resolve_shortcut(lnk)
            if not target or not target.lower().endswith(".exe"):
                continue
            name = lnk.stem.lower()
            if name not in found:
                found[name] = target
    return [{"name": n, "target": t} for n, t in sorted(found.items())]
