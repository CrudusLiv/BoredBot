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

While voice.silence says Vesper is silenced (killswitch paused, or a
silence_when_running process is up) the stream is not opened at all — being
"fully deaf" has to mean the microphone is closed, not merely that detections
are discarded.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Callable

SAMPLE_RATE = 16_000
CHUNK_SIZE = 1280  # ~80 ms at 16 kHz — openwakeword's recommended chunk

# How long to poll while silenced before re-checking whether we may listen again.
_SILENCE_POLL_S = 0.5


def _keyword_hit(text: str, keyword: str) -> bool:
    """True only when `keyword` appears as a whole word.

    Substring matching made "vespers" and "vesperine" wake her; vosk's restricted
    grammar force-aligns unrelated audio onto the nearest in-grammar token, so a
    loose match fires constantly on speech that was never the wake word."""
    if not text or not keyword:
        return False
    return re.search(rf"(?<!\w){re.escape(keyword.lower())}(?!\w)", text.lower()) is not None


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
    from voice import silence

    while stop_event is None or not stop_event.is_set():
        if silence.is_silenced():
            time.sleep(_SILENCE_POLL_S)
            continue

        buf: list[float] = []
        fired = False
        went_silent = False

        def _cb(indata, frames, time_info, status):  # noqa: ARG001
            if mute_event and mute_event.is_set():
                buf.clear()  # never feed Vesper's own voice to the model
                return
            buf.extend(indata[:, 0].tolist())

        # Open stream; break inner loop when wake word fires (closes stream).
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=CHUNK_SIZE, callback=_cb,
        ):
            while stop_event is None or not stop_event.is_set():
                if silence.is_silenced():
                    went_silent = True
                    break  # close the mic for the duration of the silence
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

        if went_silent:
            continue  # reopen once silence lifts
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

    from voice import config as _cfg, silence

    kw = keyword.lower()
    grammar = json.dumps([kw, "[unk]"])
    cooldown_s = float(_cfg.load().get("wakeword_cooldown_s", 1.5))
    print(f"[wakeword] listening for '{kw}'")

    CHUNK = 4000  # ~250 ms at 16 kHz

    while stop_event is None or not stop_event.is_set():
        if silence.is_silenced():
            time.sleep(_SILENCE_POLL_S)
            continue

        rec = KaldiRecognizer(model, SAMPLE_RATE, grammar)
        buf: list[bytes] = []
        fired = False
        went_silent = False
        # Room echo and the tail of Vesper's own reply keep arriving after
        # playback ends, so stay deaf for cooldown_s past the last muted block.
        deaf_until = [0.0]

        def _cb(indata, frames, time_info, status):  # noqa: ARG001
            if mute_event and mute_event.is_set():
                buf.clear()
                deaf_until[0] = time.monotonic() + cooldown_s
                return
            buf.append(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE, blocksize=CHUNK,
                dtype="int16", channels=1, callback=_cb,
            ):
                while stop_event is None or not stop_event.is_set():
                    if silence.is_silenced():
                        went_silent = True
                        break  # close the mic for the duration of the silence
                    if not buf:
                        time.sleep(0.02)
                        continue
                    data = buf.pop(0)
                    if time.monotonic() < deaf_until[0]:
                        rec.Reset()  # drop half-decoded audio from her own voice
                        continue
                    # Final results only. Partial hypotheses under a restricted
                    # grammar surface the keyword constantly on speech that the
                    # final result then resolves to [unk] — that was the false-wake
                    # source. Costs the length of one end-of-utterance pause.
                    if not rec.AcceptWaveform(data):
                        continue
                    text = json.loads(rec.Result()).get("text", "")
                    if _keyword_hit(text, kw):
                        fired = True
                        break  # exits inner loop → closes RawInputStream
        except Exception as exc:
            print(f"[wakeword] vosk stream error: {exc}")
            if stop_event:
                stop_event.set()
            return

        if went_silent:
            continue  # reopen once silence lifts
        if not fired:
            break  # stop_event was set

        # Stream closed — safe for main thread to call record_vad()
        callback()

        if ready_event:
            ready_event.wait()
            ready_event.clear()
        else:
            time.sleep(3.0)
