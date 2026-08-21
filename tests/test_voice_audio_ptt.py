"""Tests for push-to-talk key mapping and the GetAsyncKeyState-based
record_ptt() capture loop.

record_ptt() used to rely on a pynput keyboard hook, which only sees
keystrokes Windows routes through the normal message chain -- a foreground
window running at higher privilege (UIPI) or a fullscreen-exclusive app
can skip that chain entirely, making PTT only reliable while Vesper's own
window had focus. Polling win32api.GetAsyncKeyState reads raw global key
state instead, so these tests fake that API rather than real hardware.
"""
from __future__ import annotations

import io
import wave

import numpy as np

from voice import audio


# --------------------------------------------------------------------------
# _vk_code
# --------------------------------------------------------------------------

def test_vk_code_named_key():
    assert audio._vk_code("space") == 0x20


def test_vk_code_case_insensitive():
    assert audio._vk_code("SPACE") == audio._vk_code("space")


def test_vk_code_function_key():
    assert audio._vk_code("f1") == 0x70
    assert audio._vk_code("f12") == 0x7B


def test_vk_code_single_letter():
    assert audio._vk_code("a") == ord("A")


def test_vk_code_digit():
    assert audio._vk_code("5") == ord("5")


def test_vk_code_backtick():
    # OEM key -- VK_OEM_3 (0xC0), not ord("`") (0x60, which would
    # collide with VK_NUMPAD0). The default ptt_key.
    assert audio._vk_code("`") == 0xC0


def test_vk_code_other_oem_punctuation_not_ascii():
    # Sanity check that OEM keys are looked up, not derived from ASCII.
    assert audio._vk_code("-") == 0xBD
    assert audio._vk_code(";") == 0xBA


# --------------------------------------------------------------------------
# record_ptt
# --------------------------------------------------------------------------

class _FakeStream:
    """Stand-in for sounddevice.InputStream: yields silent blocks."""

    def __init__(self, block_size: int):
        self._data = np.zeros((block_size, 1), dtype="float32")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, block_size):
        return self._data, False


def _install_fakes(monkeypatch, down_sequence, key_vk=0x20):
    """down_sequence: bools consumed in call order, but only for key_vk
    (default VK_SPACE, matching every caller's key="space"). keys.is_down()
    queries GetAsyncKeyState once for the main key and once per modifier
    (its exactness check), so a fake that ignored the vk argument and drew
    every call from one shared queue let the modifier checks silently steal
    values meant for the main key -- desyncing the script until it exhausted
    and froze into a permanent "not down" read, hanging record_ptt's
    wait-for-press loop forever. Any other vk (i.e. every modifier) always
    reads "up", since none of these tests script a held modifier. Sticks on
    the last value once exhausted so an unexpectedly extra call doesn't
    IndexError."""
    calls = iter(down_sequence)
    last = {"v": down_sequence[-1]}

    def get_async_key_state(vk):
        if vk != key_vk:
            return 0
        try:
            last["v"] = next(calls)
        except StopIteration:
            pass
        return 0x8000 if last["v"] else 0

    fake_win32api = type("_FakeWin32Api", (), {"GetAsyncKeyState": staticmethod(get_async_key_state)})
    fake_sd = type("_FakeSd", (), {"InputStream": lambda self=None, **kw: _FakeStream(1024)})()

    import sys
    monkeypatch.setitem(sys.modules, "win32api", fake_win32api)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(audio, "POLL_INTERVAL_S", 0.0)


def test_record_ptt_returns_none_below_min_duration(monkeypatch):
    # 1 block (1024 samples @ 16kHz = 64ms) is well under the 0.5s floor.
    _install_fakes(monkeypatch, [False, True, True, False])
    result = audio.record_ptt(key="space")
    assert result is None


def test_record_ptt_returns_wav_bytes_above_min_duration(monkeypatch):
    # 10 blocks (10240 samples @ 16kHz ~= 0.64s) clears the 0.5s floor.
    down_seq = [False] + [True] * 11 + [False]
    _install_fakes(monkeypatch, down_seq)
    result = audio.record_ptt(key="space")
    assert result is not None
    with wave.open(io.BytesIO(result)) as wf:
        assert wf.getframerate() == audio.SAMPLE_RATE
        assert wf.getnchannels() == audio.CHANNELS
        assert wf.getsampwidth() == 2


def test_record_ptt_fires_on_press_once(monkeypatch):
    down_seq = [False] + [True] * 11 + [False]
    _install_fakes(monkeypatch, down_seq)
    calls = []
    audio.record_ptt(key="space", on_press=lambda: calls.append(1))
    assert calls == [1]


def test_record_ptt_swallows_on_press_exception(monkeypatch):
    down_seq = [False] + [True] * 11 + [False]
    _install_fakes(monkeypatch, down_seq)

    def boom():
        raise RuntimeError("boom")

    # Must not raise -- on_press failures shouldn't abort recording.
    result = audio.record_ptt(key="space", on_press=boom)
    assert result is not None
