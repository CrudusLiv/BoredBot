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

from voice import keys


def _vk_code(key: str) -> int:
    """Resolve a key name to a Windows VK code. See voice/keys.py."""
    return keys.vk(key)


def is_ptt_down(key: str = "space") -> bool:
    """Non-blocking check: is the PTT key (or combo) currently held?

    Polls GetAsyncKeyState for raw global key state rather than installing a
    keyboard hook. A hook only sees keystrokes Windows routes through the
    normal message chain, which UIPI (elevated foreground apps) and
    fullscreen-exclusive apps can bypass -- that made PTT only reliable
    while Vesper's own window had focus. GetAsyncKeyState isn't subject to
    either restriction.
    """
    try:
        import win32api  # noqa: F401 -- import guard for the error message below
    except ImportError as exc:
        raise RuntimeError(
            f"Voice mode requires extra deps: pip install pywin32  ({exc})"
        ) from exc
    return keys.is_down(key)


def record_while_held(key: str = "space", on_press=None) -> Optional[bytes]:
    """Record audio while the PTT key stays held. Assumes the key is
    already down when called (see is_ptt_down) — no wait-for-press loop.
    Returns WAV bytes, or None if the clip was too short to be speech.

    on_press: callable fired once, immediately. Used for barge-in: pass
    tts.stop_speaking to cancel ongoing TTS.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            f"Voice mode requires extra deps: pip install sounddevice pywin32 numpy  ({exc})"
        ) from exc

    if on_press:
        try:
            on_press()
        except Exception:
            pass

    print("  [recording...]  ", end="\r", flush=True)

    chunks: list = []
    block_size = 1024

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        while is_ptt_down(key):
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


def record_ptt(key: str = "space", on_press=None) -> Optional[bytes]:
    """Block until PTT key pressed; record while held; return WAV bytes or None.

    on_press: callable fired the instant the PTT key is first detected.
    Used for barge-in: pass tts.stop_speaking to cancel ongoing TTS.
    """
    print(f"  [hold {key} to speak]", end="\r", flush=True)
    while not is_ptt_down(key):
        time.sleep(POLL_INTERVAL_S)
    return record_while_held(key, on_press=on_press)
