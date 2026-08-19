"""Hotkey specs shared by the global key poll and the browser UI.

A spec is modifiers joined to one main key with '+': "g", "shift+f",
"ctrl+alt+g", "numpad1". Both consumers poll GetAsyncKeyState rather than
installing a hook, so a combo costs one extra read per component key.

'+' cannot be a main key here -- write "equals" or "numpad_add".
"""
from __future__ import annotations

MODIFIER_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}

# Which modifier family a key name belongs to, so a spec whose *main* key is
# itself a modifier ("shift" as push-to-talk) doesn't fail its own exactness
# check in is_down().
_FAMILY = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win", "win": "win",
}

NAMED_VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "shift_l": 0xA0, "shift_r": 0xA1,
    "ctrl": 0x11, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt": 0x12, "alt_l": 0xA4, "alt_r": 0xA5,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "page_up": 0x21, "page_down": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "delete": 0x2E,
    "cmd": 0x5B, "cmd_l": 0x5B, "cmd_r": 0x5C, "win": 0x5B,
    # OEM punctuation (US layout) -- VK codes don't match ASCII, so they
    # must be listed rather than fall through to the ord() guess.
    "`": 0xC0, "grave": 0xC0,
    "-": 0xBD, "minus": 0xBD,
    "=": 0xBB, "equals": 0xBB,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
    "numpad_multiply": 0x6A, "numpad_add": 0x6B,
    "numpad_subtract": 0x6D, "numpad_decimal": 0x6E, "numpad_divide": 0x6F,
    "numlock": 0x90,
}
NAMED_VK.update({f"numpad{i}": 0x60 + i for i in range(10)})
NAMED_VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def parse(spec: str) -> tuple[frozenset[str], str]:
    """Split a spec into (modifier names, main key name)."""
    parts = [p.strip() for p in spec.strip().lower().split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey spec")
    *mods, main = parts
    for m in mods:
        if m not in MODIFIER_VK:
            raise ValueError(f"unknown modifier {m!r} in {spec!r}")
    return frozenset(mods), main


def vk(name: str) -> int:
    """Resolve a key name to a Windows VK code."""
    named = NAMED_VK.get(name.lower())
    if named is not None:
        return named
    if not name:
        raise ValueError("empty key name")
    return ord(name[0].upper())


def _down(code: int) -> bool:
    import win32api
    return bool(win32api.GetAsyncKeyState(code) & 0x8000)


def is_down(spec: str) -> bool:
    """True when every component of `spec` is held and nothing else is.

    The exactness rule matters: without it, binding both "f" and "shift+f"
    means pressing shift+f fires both.
    """
    mods, main = parse(spec)
    if not _down(vk(main)):
        return False
    main_family = _FAMILY.get(main)
    for name, code in MODIFIER_VK.items():
        if name == main_family:
            continue
        if _down(code) != (name in mods):
            return False
    return True
