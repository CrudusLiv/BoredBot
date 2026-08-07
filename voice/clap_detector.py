"""Double-clap detector — fires a callback when two sharp transients occur
within clap_window_s seconds of each other.

Runs as a daemon thread alongside the wakeword listener. Uses its own
sounddevice InputStream (Windows WASAPI shared mode supports multiple
concurrent input streams from the same mic).

Clap detection algorithm:
  - Sample audio in 50 ms chunks
  - A "clap" = chunk whose peak amplitude exceeds threshold (default 0.3)
  - Two claps within clap_window_s (default 1.5 s) → fire callback
  - Cooldown of 0.15 s between detections prevents echo from counting twice
"""
from __future__ import annotations

import threading
import time
from typing import Callable


SAMPLE_RATE = 16_000
CHUNK_SIZE  = 800  # ~50 ms at 16 kHz


def listen(
    callback:      Callable[[], None],
    stop_event:    threading.Event,
    threshold:     float = 0.3,
    window_s:      float = 1.5,
    cooldown_s:    float = 0.15,
    mute_event:    "threading.Event | None" = None,
    post_mute_s:   float = 1.5,
) -> None:
    """Block until stop_event is set; call callback() on each double clap.

    callback:     Called in a daemon thread so it doesn't block detection.
    stop_event:   Set to exit cleanly.
    threshold:    Peak amplitude (0–1) above which a chunk counts as a clap.
    window_s:     Max gap between clap 1 and clap 2.
    cooldown_s:   Min gap between consecutive detections (prevents echo).
    mute_event:   When set, peak buffer is flushed and detection is suppressed.
    post_mute_s:  Seconds to stay deaf after mute_event clears (lets room
                  reverb settle after TTS finishes).
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        print(f"[clap] sounddevice/numpy not installed — disabled  ({exc})")
        stop_event.wait()
        return

    clap_times: list[float] = []
    # Track when mute last fired so we can add a post-speech cooldown.
    # Init to now so startup noise doesn't arm on the first second.
    _unmuted_at: list[float] = [time.monotonic()]

    def _audio_cb(indata, frames, time_info, status):  # noqa: ARG001
        now = time.monotonic()
        if mute_event and mute_event.is_set():
            clap_times.clear()
            _unmuted_at[0] = now  # keep resetting so cooldown starts from end of speech
            return
        if (now - _unmuted_at[0]) < post_mute_s:
            clap_times.clear()  # still in post-speech cooldown — room reverb settling
            return
        peak = float(np.max(np.abs(indata)))
        if peak < threshold:
            return
        # Drop claps outside the window
        while clap_times and (now - clap_times[0]) > window_s:
            clap_times.pop(0)
        # Cooldown: ignore if last detection was too recent
        if clap_times and (now - clap_times[-1]) < cooldown_s:
            return
        clap_times.append(now)
        if len(clap_times) >= 2:
            clap_times.clear()
            threading.Thread(target=callback, daemon=True).start()

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_SIZE,
            callback=_audio_cb,
        ):
            stop_event.wait()
    except Exception as exc:
        print(f"[clap] audio stream error — disabled  ({exc})")
        stop_event.wait()
