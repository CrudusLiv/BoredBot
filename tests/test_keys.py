# tests/test_keys.py
"""Hotkey spec grammar: singles, modifier combos, numpad, exactness."""
from __future__ import annotations

import pytest

from voice import keys


def test_parses_single_key():
    assert keys.parse("f") == (frozenset(), "f")


def test_parses_named_key():
    assert keys.parse("f9") == (frozenset(), "f9")


def test_parses_modifier_combo():
    assert keys.parse("shift+f") == (frozenset({"shift"}), "f")


def test_parses_multiple_modifiers():
    mods, main = keys.parse("ctrl+alt+g")
    assert mods == frozenset({"ctrl", "alt"})
    assert main == "g"


def test_parsing_is_case_and_space_insensitive():
    assert keys.parse("  CTRL + Shift + G ") == (frozenset({"ctrl", "shift"}), "g")


def test_rejects_empty_spec():
    with pytest.raises(ValueError):
        keys.parse("")


def test_rejects_unknown_modifier():
    with pytest.raises(ValueError):
        keys.parse("hyper+g")


def test_numpad_digits_resolve_to_windows_vk():
    assert keys.vk("numpad0") == 0x60
    assert keys.vk("numpad9") == 0x69


def test_numpad_operators_resolve_to_windows_vk():
    assert keys.vk("numpad_multiply") == 0x6A
    assert keys.vk("numpad_add") == 0x6B
    assert keys.vk("numpad_subtract") == 0x6D
    assert keys.vk("numpad_decimal") == 0x6E
    assert keys.vk("numpad_divide") == 0x6F


def test_existing_named_keys_still_resolve():
    assert keys.vk("`") == 0xC0
    assert keys.vk("f9") == 0x78
    assert keys.vk("space") == 0x20


def test_single_letter_falls_back_to_ascii():
    assert keys.vk("g") == ord("G")


@pytest.fixture
def held(monkeypatch):
    """Pretend a given set of VK codes is physically held down."""
    state: set[int] = set()

    def fake_down(code: int) -> bool:
        return code in state

    monkeypatch.setattr(keys, "_down", fake_down)
    return state


def test_is_down_true_when_single_key_held(held):
    held.add(ord("G"))
    assert keys.is_down("g") is True


def test_is_down_false_when_key_not_held(held):
    assert keys.is_down("g") is False


def test_is_down_true_for_combo_when_both_held(held):
    held.update({keys.MODIFIER_VK["shift"], ord("F")})
    assert keys.is_down("shift+f") is True


def test_is_down_false_for_combo_when_modifier_missing(held):
    held.add(ord("F"))
    assert keys.is_down("shift+f") is False


def test_bare_key_does_not_fire_while_modifier_held(held):
    """Exactness: 'f' must not match when shift+f is pressed."""
    held.update({keys.MODIFIER_VK["shift"], ord("F")})
    assert keys.is_down("f") is False


def test_combo_does_not_fire_with_extra_modifier(held):
    held.update({keys.MODIFIER_VK["shift"], keys.MODIFIER_VK["ctrl"], ord("F")})
    assert keys.is_down("shift+f") is False


def test_modifier_as_main_key_matches_itself(held):
    """ptt_key = 'shift' must work despite the exactness rule."""
    held.add(keys.NAMED_VK["shift"])
    assert keys.is_down("shift") is True


def test_numpad_key_is_down(held):
    held.add(0x61)
    assert keys.is_down("numpad1") is True
