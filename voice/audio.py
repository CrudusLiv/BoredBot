"""Push-to-talk audio capture via win32api + sounddevice.

Records while PTT key is held, returns WAV bytes (16kHz mono 16-bit)
for faster-whisper transcription, or None if the clip was too short to
be speech.
"""
from __future__ import annotations

import io
import time
import wave
from typing import Optional

SAMPLE_RATE = 16_000
CHANNELS = 1
MIN_DURATION_S = 0.5
POLL_INTERVAL_S = 0.01

# Windows virtual-key codes for the PTT key names this app has ever exposed
# (config default is "space"; setup docs mention others as options).
_NAMED_VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "shift_l": 0xA0, "shift_r": 0xA1,
    "ctrl": 0x11, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt": 0x12, "alt_l": 0xA4, "alt_r": 0xA5,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "page_up": 0x21, "page_down": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "delete": 0x2E,
    "cmd": 0x5B, "cmd_l": 0x5B, "cmd_r": 0x5C,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F, "f17": 0x80, "f18": 0x81,
    "f19": 0x82, "f20": 0x83, "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
}


def _vk_code(key: str) -> int:
    """Resolve a key name like 'space', 'f1', or a single char to a Windows VK code."""
    named = _NAMED_VK.get(key.lower())
    if named is not None:
        return named
    return ord(key[0].upper())


def record_ptt(key: str = "space", on_press=None) -> Optional[bytes]:
    """Block until PTT key pressed; record while held; return WAV bytes or None.

    on_press: callable fired the instant the PTT key is first detected.
    Used for barge-in: pass tts.stop_speaking to cancel ongoing TTS.

    Polls win32api.GetAsyncKeyState for raw global key state rather than
    installing a keyboard hook. A hook only sees keystrokes Windows routes
    through the normal message chain, which UIPI (elevated foreground apps)
    and fullscreen-exclusive apps can bypass — that made PTT only reliable
    while Vesper's own window had focus. GetAsyncKeyState isn't subject to
    either restriction.
    """
    try:
        import numpy as np
        import sounddevice as sd
        import win32api
    except ImportError as exc:
        raise RuntimeError(
            f"Voice mode requires extra deps: pip install sounddevice pywin32 numpy  ({exc})"
        ) from exc

    vk = _vk_code(key)

    def is_down() -> bool:
        return bool(win32api.GetAsyncKeyState(vk) & 0x8000)

    print(f"  [hold {key} to speak]", end="\r", flush=True)

    while not is_down():
        time.sleep(POLL_INTERVAL_S)

    if on_press:
        try:
            on_press()
        except Exception:
            pass

    print("  [recording...]  ", end="\r", flush=True)

    chunks: list = []
    block_size = 1024

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        while is_down():
            data, _ = stream.read(block_size)
            chunks.append(data.copy())
            # Emit RMS amplitude for the mic volume ring in the orb UI
            try:
                import numpy as _np
                rms = float(_np.sqrt(_np.mean(data ** 2)))
                from voice import ui_server as _ui
                _ui.post_event({"type": "amplitude", "value": rms})
            except Exception:
                pass

    print("                    ", end="\r", flush=True)

    if not chunks:
        return None

    import numpy as np

    audio = np.concatenate(chunks, axis=0)
    if len(audio) < SAMPLE_RATE * MIN_DURATION_S:
        return None

    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()
