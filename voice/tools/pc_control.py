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
