"""Wake-word detection — two backends selectable via config.json.

Backend 1 (default): openwakeword
  - Built-in models: alexa, hey_mycroft, hey_jarvis, hey_rhasspy
  - Install: pip install openwakeword sounddevice numpy
  - Config: wakeword_engine "openwakeword", wakeword_model "<name or .onnx>"

Backend 2: vosk keyword spotter  ← use this for "vesper"
  - Free, offline, no training, no account needed
  - First run auto-downloads vosk-model-small-en-us-0.15 (~50 MB)
  - Install: py -m pip install vosk
  - Config: wakeword_engine "vosk", wakeword_keyword "vesper"

IMPORTANT: the sounddevice stream is *closed* before callback() fires so
that record_vad() can open its own stream. If ready_event is passed the
wakeword thread waits for it before reopening — set it after VAD finishes.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

SAMPLE_RATE = 16_000
CHUNK_SIZE = 1280  # ~80 ms at 16 kHz — openwakeword's recommended chunk


def listen(
    callback: Callable[[], None],
    stop_event: threading.Event | None = None,
    model_path: str = "",
    threshold: float = 0.5,
    ready_event: threading.Event | None = None,
    mute_event: threading.Event | None = None,
) -> None:
    """Block; call callback() each time the wake word fires.

    callback:    Called with the stream CLOSED so record_vad() can open its own.
    stop_event:  Set to exit cleanly.
    model_path:  .onnx path or openwakeword model name; falls back to 'alexa'.
    threshold:   Detection confidence 0–1.
    ready_event: Main thread sets this after VAD recording finishes.
                 Wakeword waits on it before reopening the stream.
    mute_event:  When set, detections are skipped (e.g. while Vesper is speaking).
    """
    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model  # type: ignore
    except ImportError as exc:
        print(f"[wakeword] openwakeword not installed — falling back to PTT  ({exc})")
        if stop_event:
            stop_event.set()
        return

    if not model_path:
        print(
            "[wakeword] no model configured — set wakeword_model in config.json\n"
            "  Download models: "
            'py -c "from openwakeword.utils import download_models; download_models()"'
        )
        if stop_event:
            stop_event.set()
        return

    _name = model_path
    try:
        oww = Model(wakeword_models=[_name], inference_framework="onnx")
    except Exception as _e1:
        print(
            f"[wakeword] model load failed ({_e1}) — run:\n"
            f'  py -c "from openwakeword.utils import download_models; download_models()"'
        )
        if stop_event:
            stop_event.set()
        return

    score_key = list(oww.models.keys())[0]

    while stop_event is None or not stop_event.is_set():
        buf: list[float] = []
        fired = False

        def _cb(indata, frames, time_info, status):  # noqa: ARG001
            buf.extend(indata[:, 0].tolist())

        # Open stream; break inner loop when wake word fires (closes stream).
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=CHUNK_SIZE, callback=_cb,
        ):
            while stop_event is None or not stop_event.is_set():
                if len(buf) < CHUNK_SIZE:
                    time.sleep(0.02)
                    continue
                chunk = np.array(buf[:CHUNK_SIZE], dtype=np.float32)
                del buf[:CHUNK_SIZE]  # in-place so _cb closure stays valid
                pcm = (chunk * 32767).astype(np.int16)
                score = oww.predict(pcm).get(score_key, 0.0)
                if score >= threshold:
                    if mute_event and mute_event.is_set():
                        continue  # Vesper is speaking — ignore
                    fired = True
                    break  # exits inner loop → with-block closes the stream

        if not fired:
            break  # stop_event was set

        # Stream is now CLOSED. Safe for main thread to call record_vad().
        callback()

        # Wait until main thread signals recording is done, then reopen stream.
        if ready_event:
            ready_event.wait()
            ready_event.clear()
        else:
            from voice import config as _cfg
            _debounce = float(_cfg.load().get("wakeword_debounce_s", 1.5))
            time.sleep(_debounce)


def listen_vosk(
    callback: Callable[[], None],
    stop_event: threading.Event | None = None,
    keyword: str = "vesper",
    model_path: str = "",
    ready_event: threading.Event | None = None,
    mute_event: threading.Event | None = None,
) -> None:
    """Vosk keyword spotter — free, offline, no training, no account.

    First run auto-downloads vosk-model-small-en-us-0.15 (~50 MB) to
    ~/.cache/vosk/. Set model_path to a local directory to skip download.
    """
    import json
    import os

    try:
        from vosk import Model, KaldiRecognizer  # type: ignore
        import sounddevice as sd
    except ImportError as exc:
        print(f"[wakeword] vosk not installed — py -m pip install vosk  ({exc})")
        if stop_event:
            stop_event.set()
        return

    _model_spec = model_path or "vosk-model-small-en-us-0.15"
    print(f"[wakeword] loading vosk model '{_model_spec}' (first run downloads ~50 MB) …")
    try:
        if os.path.isdir(_model_spec):
            model = Model(_model_spec)
        else:
            model = Model(model_name=_model_spec)
    except Exception as exc:
        print(f"[wakeword] vosk model load failed: {exc}")
        if stop_event:
            stop_event.set()
        return

    kw = keyword.lower()
    grammar = json.dumps([kw, "[unk]"])
    print(f"[wakeword] listening for '{kw}'")

    CHUNK = 4000  # ~250 ms at 16 kHz

    while stop_event is None or not stop_event.is_set():
        rec = KaldiRecognizer(model, SAMPLE_RATE, grammar)
        buf: list[bytes] = []
        fired = False

        def _cb(indata, frames, time_info, status):  # noqa: ARG001
            if mute_event and mute_event.is_set():
                return
            buf.append(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE, blocksize=CHUNK,
                dtype="int16", channels=1, callback=_cb,
            ):
                while stop_event is None or not stop_event.is_set():
                    if not buf:
                        time.sleep(0.02)
                        continue
                    data = buf.pop(0)
                    if rec.AcceptWaveform(data):
                        text = json.loads(rec.Result()).get("text", "").lower()
                    else:
                        text = json.loads(rec.PartialResult()).get("partial", "").lower()
                    if kw in text:
                        fired = True
                        break  # exits inner loop → closes RawInputStream
        except Exception as exc:
            print(f"[wakeword] vosk stream error: {exc}")
            if stop_event:
                stop_event.set()
            return

        if not fired:
            break  # stop_event was set

        # Stream closed — safe for main thread to call record_vad()
        callback()

        if ready_event:
            ready_event.wait()
            ready_event.clear()
        else:
            time.sleep(3.0)
