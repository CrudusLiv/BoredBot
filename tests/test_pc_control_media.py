"""voice/tools/pc_control.py::media_control, set_volume.
win32api key-event simulation and pycaw volume control are both mocked --
these tests never touch real audio hardware or send real key events."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from voice.tools import pc_control


def test_media_control_play_pause_sends_correct_vk():
    with patch("win32api.keybd_event") as mock_kb:
        result = pc_control.media_control("play_pause")
    assert "play" in result.lower() or "pause" in result.lower()
    vks_pressed = [call.args[0] for call in mock_kb.call_args_list]
    assert pc_control._MEDIA_VK["play_pause"] in vks_pressed


def test_media_control_next_sends_correct_vk():
    with patch("win32api.keybd_event") as mock_kb:
        pc_control.media_control("next")
    vks_pressed = [call.args[0] for call in mock_kb.call_args_list]
    assert pc_control._MEDIA_VK["next"] in vks_pressed


def test_media_control_unknown_action_returns_error_without_raising():
    with patch("win32api.keybd_event") as mock_kb:
        result = pc_control.media_control("moonwalk")
    assert "unknown" in result.lower()
    mock_kb.assert_not_called()


def test_media_control_key_down_then_up():
    with patch("win32api.keybd_event") as mock_kb:
        pc_control.media_control("mute")
    assert mock_kb.call_count == 2
    down_call, up_call = mock_kb.call_args_list
    assert down_call.args[2] == 0  # KEYEVENTF_KEYDOWN (flags=0)
    assert up_call.args[2] != 0    # KEYEVENTF_KEYUP


def test_set_volume_clamps_high_value():
    fake_endpoint = MagicMock()
    with patch.object(pc_control, "_volume_endpoint", return_value=fake_endpoint):
        result = pc_control.set_volume(150)
    fake_endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(1.0, None)
    assert "100" in result


def test_set_volume_clamps_negative_value():
    fake_endpoint = MagicMock()
    with patch.object(pc_control, "_volume_endpoint", return_value=fake_endpoint):
        result = pc_control.set_volume(-10)
    fake_endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.0, None)
    assert "0" in result


def test_set_volume_sets_scalar_fraction():
    fake_endpoint = MagicMock()
    with patch.object(pc_control, "_volume_endpoint", return_value=fake_endpoint):
        result = pc_control.set_volume(60)
    fake_endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.6, None)
    assert "60" in result
