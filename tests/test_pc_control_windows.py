"""voice/tools/pc_control.py::list_windows, focus_window.
win32gui enumeration and foreground-window calls are mocked -- these tests
never enumerate or focus real OS windows."""
from __future__ import annotations

from unittest.mock import patch

from voice.tools import pc_control


def test_list_windows_returns_visible_titles():
    windows = [(1, "Notepad"), (2, "Vesper"), (3, "")]  # blank titles are skipped

    def fake_enum(callback, extra):
        for hwnd, title in windows:
            with patch("win32gui.IsWindowVisible", return_value=True), \
                 patch("win32gui.GetWindowText", return_value=title):
                callback(hwnd, extra)

    with patch("win32gui.EnumWindows", side_effect=fake_enum):
        result = pc_control.list_windows()
    assert "Notepad" in result
    assert "Vesper" in result


def test_list_windows_skips_invisible_windows():
    def fake_enum(callback, extra):
        with patch("win32gui.IsWindowVisible", return_value=False), \
             patch("win32gui.GetWindowText", return_value="Hidden"):
            callback(1, extra)

    with patch("win32gui.EnumWindows", side_effect=fake_enum):
        result = pc_control.list_windows()
    assert "Hidden" not in result


def test_focus_window_matches_substring_case_insensitive():
    def fake_enum(callback, extra):
        with patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.GetWindowText", return_value="Mozilla Firefox"):
            callback(42, extra)

    with patch("win32gui.EnumWindows", side_effect=fake_enum), \
         patch("win32gui.ShowWindow") as mock_show, \
         patch("win32gui.SetForegroundWindow") as mock_focus:
        result = pc_control.focus_window("firefox")

    mock_show.assert_called_once()
    mock_focus.assert_called_once_with(42)
    assert "firefox" in result.lower() or "mozilla" in result.lower()


def test_focus_window_no_match_returns_error_without_calling_focus():
    def fake_enum(callback, extra):
        with patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.GetWindowText", return_value="Notepad"):
            callback(1, extra)

    with patch("win32gui.EnumWindows", side_effect=fake_enum), \
         patch("win32gui.SetForegroundWindow") as mock_focus:
        result = pc_control.focus_window("spotify")

    mock_focus.assert_not_called()
    assert "no window" in result.lower() or "not found" in result.lower()
