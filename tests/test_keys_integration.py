# tests/test_keys_integration.py
"""audio.py and screen_read_hotkeys.py must resolve keys via voice.keys."""
from __future__ import annotations

from voice import audio, keys, screen_read_hotkeys


def test_audio_vk_code_delegates_to_keys():
    assert audio._vk_code("f9") == keys.vk("f9")
    assert audio._vk_code("`") == keys.vk("`")


def test_audio_vk_code_supports_numpad():
    assert audio._vk_code("numpad1") == 0x61


def test_ptt_accepts_a_combo(monkeypatch):
    held = {keys.MODIFIER_VK["shift"], ord("F")}
    monkeypatch.setattr(keys, "_down", lambda c: c in held)
    assert audio.is_ptt_down("shift+f") is True


def test_screen_read_is_down_supports_combo(monkeypatch):
    held = {keys.MODIFIER_VK["ctrl"], 0x78}
    monkeypatch.setattr(keys, "_down", lambda c: c in held)
    assert screen_read_hotkeys._is_down("ctrl+f9") is True
