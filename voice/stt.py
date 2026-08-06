"""Speech-to-text.

faster-whisper (local, offline, no API key required).

Config keys (voice/config.json):
  stt_model           "tiny" | "base" | "small" | "medium" | "large-v3"  (default "base")
  stt_device          "cpu" | "cuda"  (default "cpu")
  stt_compute_type    "int8" | "float16" | "float32"  (default "int8")
  stt_beam_size       1 = fastest, 5 = most accurate  (default 1)
  stt_vad_filter      skip silence segments  (default true)
  stt_vad_min_silence_ms  silence gap in ms  (default 300)
  stt_language        BCP-47 code e.g. "en"  (default "en")
"""
from __future__ import annotations

import io
import wave

_model = None  # lazy singleton — loaded on first transcribe() call


def _load_model():
    global _model
    if _model is not None:
        return _model

    from voice import config as cfg
    conf = cfg.load()
    model_name   = conf.get("stt_model", "base")
    device       = conf.get("stt_device", "cpu")
    compute_type = conf.get("stt_compute_type", "int8")

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(f"pip install faster-whisper  ({exc})") from exc

    print(f"[STT] loading faster-whisper '{model_name}' ({device}/{compute_type}) …", flush=True)
    try:
        _model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:
        if device != "cpu":
            print(f"[STT] {device} init failed ({exc}) — retrying on cpu/int8", flush=True)
            _model = WhisperModel(model_name, device="cpu", compute_type="int8")
        else:
            raise
    print("[STT] model ready.", flush=True)
    return _model


def _wav_to_float32(audio_bytes: bytes):
    """Decode 16kHz mono int16 WAV bytes to float32 numpy array."""
    import numpy as np
    buf = io.BytesIO(audio_bytes)
    with wave.open(buf) as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe WAV bytes; returns the recognised string (may be empty)."""
    model = _load_model()
    audio = _wav_to_float32(audio_bytes)
    from voice import config as cfg
    conf = cfg.load()
    segments, _ = model.transcribe(
        audio,
        beam_size=int(conf.get("stt_beam_size", 1)),
        language=conf.get("stt_language", "en"),
        vad_filter=bool(conf.get("stt_vad_filter", True)),
        vad_parameters={
            "min_silence_duration_ms": int(conf.get("stt_vad_min_silence_ms", 300)),
        },
        condition_on_previous_text=False,
    )
    return " ".join(seg.text for seg in segments).strip()
