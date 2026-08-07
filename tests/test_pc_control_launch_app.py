"""voice/tools/pc_control.py::launch_app — allowlist-only. A name not in
voice/config.py's pc_control_apps must never reach os.startfile(); voice
commands pass through STT first, so this is the guard against a misheard
or injected instruction starting an arbitrary program."""
from __future__ import annotations

from unittest.mock import patch

from voice import config as cfg
from voice.tools import pc_control

CONF = {"pc_control_apps": {"spotify": "spotify:", "notepad": "notepad.exe"}}


def test_launch_allowlisted_app_calls_startfile(monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    with patch("os.startfile") as mock_start:
        result = pc_control.launch_app("notepad")
    mock_start.assert_called_once_with("notepad.exe")
    assert "notepad" in result.lower()


def test_launch_allowlisted_app_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    with patch("os.startfile") as mock_start:
        pc_control.launch_app("Spotify")
    mock_start.assert_called_once_with("spotify:")


def test_launch_non_allowlisted_app_does_not_call_startfile(monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    with patch("os.startfile") as mock_start:
        result = pc_control.launch_app("cmd")
    mock_start.assert_not_called()
    assert "not allowed" in result.lower() or "not in" in result.lower()


def test_launch_with_empty_allowlist_refuses_everything(monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: {"pc_control_apps": {}})
    with patch("os.startfile") as mock_start:
        result = pc_control.launch_app("notepad")
    mock_start.assert_not_called()
    assert "not allowed" in result.lower() or "not in" in result.lower()


def test_launch_startfile_error_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    with patch("os.startfile", side_effect=OSError("file not found")):
        result = pc_control.launch_app("notepad")
    assert "error" in result.lower() or "failed" in result.lower()
