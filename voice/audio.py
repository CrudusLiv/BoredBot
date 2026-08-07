"""Push-to-talk audio capture via pynput + sounddevice.

Records while PTT key is held, returns WAV bytes (16kHz mono 16-bit)
ready for Deepgram, or None if the clip was too short to be speech.
"""
from __future__ import annotations

import io
import threading
import wave
from typing import Optional

SAMPLE_RATE = 16_000
CHANNELS = 1
MIN_DURATION_S = 0.5


def record_ptt(key: str = "space", on_press=None) -> Optional[bytes]:
    """Block until PTT key pressed; record while held; return WAV bytes or None.

    on_press: callable fired the instant the PTT key is first detected.
    Used for barge-in: pass tts.stop_speaking to cancel ongoing TTS.
    """
    try:
        import numpy as np
        import sounddevice as sd
        from pynput import keyboard
    except ImportError as exc:
        raise RuntimeError(
            f"Voice mode requires extra deps: pip install sounddevice pynput numpy  ({exc})"
        ) from exc

    pressed = threading.Event()
    released = threading.Event()
    key_obj = _parse_key(key, keyboard)

    def on_press_handler(k: object) -> None:
        if k == key_obj:
            pressed.set()
            if on_press:
                try:
                    on_press()
                except Exception:
                    pass

    def on_release(k: object) -> bool | None:
        if k == key_obj:
            released.set()
            return False  # stop listener

    print(f"  [hold {key} to speak]", end="\r", flush=True)

    chunks: list = []
    block_size = 1024

    with keyboard.Listener(on_press=on_press_handler, on_release=on_release):
        pressed.wait()
        print("  [recording...]  ", end="\r", flush=True)
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
            while not released.is_set():
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


def record_vad() -> Optional[bytes]:
    """Record immediately; stop when silence detected. Used after wake-word trigger.

    Timing controlled by config: vad_silence_s (default 0.6), vad_max_s (default 8),
    vad_silence_threshold (default 0.01).

    Returns WAV bytes or None if the clip is too short.
    """
    try:
        from voice import config as _cfg
        _conf = _cfg.load()
        max_duration_s     = float(_conf.get("vad_max_s", 8.0))
        silence_threshold  = float(_conf.get("vad_silence_threshold", 0.01))
        silence_duration_s = float(_conf.get("vad_silence_s", 0.6))
    except Exception:
        max_duration_s, silence_threshold, silence_duration_s = 8.0, 0.01, 0.6
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(f"Voice mode requires sounddevice numpy  ({exc})") from exc

    block = 1024
    silence_blocks_needed = max(1, int(silence_duration_s * SAMPLE_RATE / block))
    max_blocks = int(max_duration_s * SAMPLE_RATE / block)

    chunks: list = []
    silence_count = 0
    speech_started = False

    print("  [listening...]  ", end="\r", flush=True)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        for _ in range(max_blocks):
            data, _ = stream.read(block)
            chunks.append(data.copy())
            rms = float(np.sqrt(np.mean(data ** 2)))
            # Emit amplitude for mic ring
            try:
                from voice import ui_server as _ui
                _ui.post_event({"type": "amplitude", "value": rms})
            except Exception:
                pass
            if rms >= silence_threshold:
                speech_started = True
                silence_count = 0
            elif speech_started:
                silence_count += 1
                if silence_count >= silence_blocks_needed:
                    break

    print("                    ", end="\r", flush=True)

    if not chunks:
        return None

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


def _parse_key(key: str, keyboard_module: object) -> object:
    """Parse a key name like 'space', 'f1', or a single char into a pynput key."""
    km = keyboard_module
    try:
        return km.Key[key.lower()]  # type: ignore[attr-defined]
    except KeyError:
        return km.KeyCode.from_char(key[0])  # type: ignore[attr-defined]
