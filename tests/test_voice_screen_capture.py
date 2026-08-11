"""Tests for voice/screen_capture.py::capture_active_monitor.
windows_capture and win32 calls are mocked -- these tests never touch a
real monitor or the WGC API."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from voice import screen_capture


def _install_fake_windows_capture(png_bytes: bytes, *, times_out: bool = False):
    """Builds a fake windows_capture module whose WindowsCapture.start()
    synchronously fires on_frame_arrived (writing png_bytes to whatever
    path save_as_image() is called with) unless times_out is True."""
    fake_module = types.ModuleType("windows_capture")

    class FakeFrame:
        def save_as_image(self, path):
            with open(path, "wb") as f:
                f.write(png_bytes)

    class FakeCaptureControl:
        def stop(self):
            pass

    class FakeWindowsCapture:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._frame_cb = None
            self._closed_cb = None

        def event(self, fn):
            if fn.__name__ == "on_frame_arrived":
                self._frame_cb = fn
            elif fn.__name__ == "on_closed":
                self._closed_cb = fn
            return fn

        def start(self):
            if times_out:
                return  # never calls back -- simulates a hang
            self._frame_cb(FakeFrame(), FakeCaptureControl())

    fake_module.WindowsCapture = FakeWindowsCapture
    fake_module.Frame = FakeFrame
    fake_module.InternalCaptureControl = FakeCaptureControl
    return fake_module


def test_capture_active_monitor_returns_saved_frame_bytes(monkeypatch):
    monkeypatch.setitem(sys.modules, "windows_capture", _install_fake_windows_capture(b"PNGDATA"))
    with patch("win32gui.GetForegroundWindow", return_value=123), \
         patch("win32api.MonitorFromWindow", return_value=999), \
         patch("win32api.EnumDisplayMonitors", return_value=[(999, None, None)]):
        result = screen_capture.capture_active_monitor()
    assert result == b"PNGDATA"


def test_capture_active_monitor_picks_correct_monitor_index(monkeypatch):
    captured_kwargs = {}
    fake_module = _install_fake_windows_capture(b"PNGDATA")
    original_init = fake_module.WindowsCapture.__init__

    def capturing_init(self, **kwargs):
        captured_kwargs.update(kwargs)
        original_init(self, **kwargs)

    fake_module.WindowsCapture.__init__ = capturing_init
    monkeypatch.setitem(sys.modules, "windows_capture", fake_module)

    # Foreground window is on the second enumerated monitor (HMONITOR 222)
    with patch("win32gui.GetForegroundWindow", return_value=123), \
         patch("win32api.MonitorFromWindow", return_value=222), \
         patch("win32api.EnumDisplayMonitors", return_value=[(111, None, None), (222, None, None)]):
        screen_capture.capture_active_monitor()

    assert captured_kwargs["monitor_index"] == 2  # 1-based, second entry


def test_capture_active_monitor_raises_on_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "windows_capture", None)
    with pytest.raises(RuntimeError, match="windows-capture"):
        screen_capture.capture_active_monitor()


def test_capture_active_monitor_raises_on_timeout(monkeypatch):
    monkeypatch.setitem(sys.modules, "windows_capture", _install_fake_windows_capture(b"", times_out=True))
    with patch("win32gui.GetForegroundWindow", return_value=123), \
         patch("win32api.MonitorFromWindow", return_value=999), \
         patch("win32api.EnumDisplayMonitors", return_value=[(999, None, None)]), \
         patch("voice.screen_capture._CAPTURE_TIMEOUT_S", 0.05):
        with pytest.raises(RuntimeError, match="timed out"):
            screen_capture.capture_active_monitor()
