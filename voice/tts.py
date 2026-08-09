"""Text-to-speech — four backends selectable via config `tts_engine`.

chatterbox (default): Chatterbox Turbo (Resemble AI) — local, GPU-accelerated, open-source.
  Install: py -m pip install chatterbox-tts
  Config: tts_chatterbox_device  ("cuda" or "cpu", default "cuda"; falls back to cpu on init failure)

edge: Microsoft Edge TTS — free, requires internet.
  Config: tts_voice  (e.g. "en-GB-SoniaNeural")

kokoro: Local Kokoro TTS — offline, no API key, high quality.
  Install: py -m pip install kokoro soundfile
  Config: tts_kokoro_voice  (e.g. "bf_isabella")
  First run downloads ~300 MB of model weights to ~/.cache/huggingface/.

elevenlabs: ElevenLabs API (ELEVENLABS_API_KEY + elevenlabs_voice_id).

Two playback modes:
  speak(text)            — single-shot: synth whole text, play (unchanged API)
  begin_utterance()      — pipelined: feed() sentences as they stream from the
                           brain; sentence N+1 synthesizes while N plays.
"""
from __future__ import annotations

import asyncio
import ctypes
import queue
import random
import re
import tempfile
import threading
from pathlib import Path

_VOWEL_RE = re.compile(r"[aeiouyAEIOUY]+")


def _syllable_count(text: str) -> int:
    """Rough syllable estimate: one vowel-letter group per word, floored at 1."""
    words = text.split()
    if not words:
        return 1
    return sum(max(1, len(_VOWEL_RE.findall(w))) for w in words)


def _estimate_envelope(text: str, duration_s: float, hz: float = 25.0) -> list[float]:
    """Synthetic mouth-open amplitude envelope (0-1), sampled at `hz`, spread
    evenly across `duration_s` -- one triangular open/close pulse per
    estimated syllable. No real audio decode (see plan Task 6 for why:
    edge-tts/ElevenLabs only produce MP3 and this app has no MP3 decoder
    dependency); "roughly in time" is the acceptance bar, not exact."""
    if duration_s <= 0:
        return []
    n_samples = max(1, round(duration_s * hz))
    syllables = _syllable_count(text)
    pulse_period = duration_s / syllables
    envelope = []
    for i in range(n_samples):
        t = i / hz
        phase = (t % pulse_period) / pulse_period
        amp = max(0.0, 1.0 - abs(phase - 0.5) * 2.0) ** 1.5
        envelope.append(round(amp, 3))
    return envelope


_alias_lock = threading.Lock()
_current_alias: str | None = None

# Serializes MCI playback so a proactive speak() and an utterance can't overlap audibly
_playback_lock = threading.Lock()

# Set while audio is physically playing — clap detector imports this to suppress self-triggering
speaking = threading.Event()

_kokoro_pipeline = None
_chatterbox_model = None

_active_utterance: "Utterance | None" = None
_utterance_lock = threading.Lock()


def speak(text: str, on_done=None, force: bool = False) -> None:
    """Synthesise and play in a daemon thread (non-blocking).

    on_done: optional zero-arg callable fired after playback ends or fails.
    force:   Speak even while silenced. Reserved for the killswitch
             acknowledgement — the one line that has to be heard *because*
             she is going quiet.

    Otherwise the text is dropped while silenced, but on_done still fires:
    callers hang the wake-word ready_event off it, so skipping it would strand
    the listener.
    """
    from voice import silence
    if not force and silence.is_silenced():
        if on_done:
            on_done()
        return
    threading.Thread(target=_play, args=(text, on_done), daemon=True).start()


def stop_speaking() -> None:
    """Interrupt current playback and cancel any active utterance (best-effort)."""
    with _utterance_lock:
        utt = _active_utterance
    if utt is not None:
        utt.cancel()
        return  # cancel() already stops the current alias
    with _alias_lock:
        alias = _current_alias
    if alias:
        try:
            _mci(f"stop {alias}")
        except Exception:
            pass


# ── Pipelined utterance (sentence streaming) ─────────────────────────────────

class Utterance:
    """Feed sentences in as they arrive; playback runs sequentially while the
    next sentence synthesizes. on_done fires exactly once — after the last
    sentence plays, or on cancel/failure."""

    def __init__(self, on_done=None) -> None:
        from voice import config as cfg
        conf = cfg.load()
        # ElevenLabs batching (credit conservation, see _synth_loop): only
        # engaged for the elevenlabs engine — edge/kokoro stay per-sentence.
        self._batch_engine = conf.get("tts_engine", "edge") == "elevenlabs"
        self._batch_chars = int(conf.get("elevenlabs_batch_chars", 250))

        self._on_done = on_done
        self._synth_q: "queue.Queue[str | None]" = queue.Queue()
        self._play_q: "queue.Queue[tuple[str, str, str] | None]" = queue.Queue()
        self._cancelled = threading.Event()
        self._done_fired = threading.Event()
        threading.Thread(target=self._synth_loop, daemon=True,
                         name="vesper-utt-synth").start()
        threading.Thread(target=self._play_loop, daemon=True,
                         name="vesper-utt-play").start()

    def feed(self, text: str) -> None:
        if text and text.strip() and not self._cancelled.is_set():
            self._synth_q.put(text.strip())

    def close(self) -> None:
        """No more sentences. on_done fires after the last one finishes."""
        self._synth_q.put(None)

    def cancel(self) -> None:
        """Stop current playback, drop everything queued, fire on_done."""
        self._cancelled.set()
        with _alias_lock:
            alias = _current_alias
        if alias:
            try:
                _mci(f"stop {alias}")
            except Exception:
                pass
        for item in _drain(self._play_q):
            if item:
                Path(item[0]).unlink(missing_ok=True)
        _drain(self._synth_q)
        self._synth_q.put(None)   # wake loops blocked on get()
        self._play_q.put(None)
        self._fire_done()

    def _synth_loop(self) -> None:
        # ElevenLabs credit conservation: the free tier bills per character
        # request, so firing one call per (short) sentence drains it fast.
        # For elevenlabs only, accumulate fed sentences into `buf` until it
        # reaches elevenlabs_batch_chars before synthesizing — trading a
        # little first-audio latency for far fewer/larger API calls. edge
        # and kokoro are free/local, so they keep synthesizing per sentence
        # for lowest latency (unchanged behaviour). Buffering happens only
        # here, single-threaded, so sentence order into _play_q is preserved
        # either way — no reordering, no deadlock risk.
        buf = ""
        while True:
            text = self._synth_q.get()
            if text is None or self._cancelled.is_set():
                # End of utterance (or cancel): flush whatever's buffered
                # rather than dropping the tail of a batch. Skip on cancel —
                # cancel() already drains/cleans up both queues.
                if buf and not self._cancelled.is_set():
                    self._synth_one(buf)
                self._play_q.put(None)
                return

            if self._batch_engine and self._batch_chars > 0:
                buf = f"{buf} {text}".strip() if buf else text
                if len(buf) < self._batch_chars:
                    continue
                text, buf = buf, ""

            if not self._synth_one(text):
                return

    def _synth_one(self, text: str) -> bool:
        """Synthesize `text` and enqueue it for playback. Returns False if the
        loop should stop (cancelled during/after synth)."""
        try:
            item = _synth(text)
        except Exception as exc:
            print(f"[TTS] synth failed: {exc}", flush=True)
            item = None
        if item:
            if self._cancelled.is_set():
                Path(item[0]).unlink(missing_ok=True)
                self._play_q.put(None)
                return False
            self._play_q.put((*item, text))
        else:
            print(f"[TTS] dropped {len(text)} chars — synth returned no audio", flush=True)
        return True

    def _play_loop(self) -> None:
        try:
            while True:
                item = self._play_q.get()
                if item is None or self._cancelled.is_set():
                    if item:
                        Path(item[0]).unlink(missing_ok=True)
                    return
                path, mci_type, text = item
                with _playback_lock:
                    if self._cancelled.is_set():
                        Path(path).unlink(missing_ok=True)
                        return
                    _utt_play(path, mci_type, text)
        finally:
            speaking.clear()
            self._fire_done()

    def _fire_done(self) -> None:
        if self._done_fired.is_set():
            return
        self._done_fired.set()
        if self._on_done:
            try:
                self._on_done()
            except Exception:
                pass


def begin_utterance(on_done=None) -> Utterance:
    """Start a pipelined utterance, cancelling any previous one.

    While silenced, hand back an already-cancelled utterance: feed() drops every
    sentence and on_done has already fired, so callers stream into it as usual
    without needing their own gate."""
    global _active_utterance
    from voice import silence
    with _utterance_lock:
        if _active_utterance is not None:
            _active_utterance.cancel()
        utt = Utterance(on_done)
        if silence.is_silenced():
            utt.cancel()
            return utt
        _active_utterance = utt
        return utt


def _drain(q: queue.Queue) -> list:
    items = []
    try:
        while True:
            items.append(q.get_nowait())
    except queue.Empty:
        pass
    return items


# ── Backend dispatch ──────────────────────────────────────────────────────────

def _synth(text: str) -> tuple[str, str] | None:
    """Synthesise text to a temp audio file with the configured engine.
    Returns (tmp_path, mci_type) or None on failure."""
    import os
    from voice import config as cfg
    conf = cfg.load()
    engine = conf.get("tts_engine", "edge")
    if engine == "elevenlabs":
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        voice_id = conf.get("elevenlabs_voice_id", "").strip()
        if api_key and voice_id:
            item = _synth_elevenlabs(text, voice_id, api_key)
            if item is not None:
                return item
            # Runtime failure (401/429/network — _synth_elevenlabs already
            # logged the specific error) rather than missing key/voice_id:
            # fall back to edge-tts so the reply is still spoken instead of
            # silently dropped.
            print("[TTS] elevenlabs failed, falling back to edge", flush=True)
            return _synth_edge(text, conf.get("tts_voice", "en-GB-SoniaNeural"))
        # key or voice_id missing — fall through to edge
    if engine == "chatterbox":
        item = _synth_chatterbox(text, conf.get("tts_chatterbox_device", "cuda"))
        if item is not None:
            return item
        print("[TTS] chatterbox failed, falling back to edge", flush=True)
        return _synth_edge(text, conf.get("tts_voice", "en-GB-SoniaNeural"))
    if engine == "kokoro":
        return _synth_kokoro(text, conf.get("tts_kokoro_voice", "bf_isabella"))
    return _synth_edge(text, conf.get("tts_voice", "en-GB-SoniaNeural"))


def _play(text: str, on_done=None) -> None:
    item = None
    try:
        item = _synth(text)
    except Exception as exc:
        print(f"[TTS] synth failed: {exc}", flush=True)
    if item is None:
        if on_done:
            on_done()
        return
    _mci_play(item[0], item[1], text, on_done)


# ── ElevenLabs backend ───────────────────────────────────────────────────────

def _synth_elevenlabs(text: str, voice_id: str, api_key: str) -> tuple[str, str] | None:
    import urllib.request
    import json as _json
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = _json.dumps({
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            mp3 = resp.read()
    except Exception as exc:
        print(f"[TTS] ElevenLabs fetch failed: {exc}", flush=True)
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fh:
        fh.write(mp3)
        return fh.name, "mpegvideo"


# ── Edge TTS backend ──────────────────────────────────────────────────────────

def _synth_edge(text: str, voice: str) -> tuple[str, str] | None:
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        print(f"[TTS] pip install edge-tts  ({exc})", flush=True)
        return None

    try:
        mp3 = asyncio.run(_fetch_edge(text, voice))
    except Exception as exc:
        print(f"[TTS] edge fetch failed: {exc}", flush=True)
        return None

    if not mp3:
        print("[TTS] edge returned empty audio — check tts_voice in config.json", flush=True)
        return None

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fh:
        fh.write(mp3)
        return fh.name, "mpegvideo"


async def _fetch_edge(text: str, voice: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


# ── Kokoro backend ────────────────────────────────────────────────────────────

def _load_kokoro(lang_code: str):
    global _kokoro_pipeline
    if _kokoro_pipeline is not None:
        return _kokoro_pipeline
    try:
        from kokoro import KPipeline
    except ImportError as exc:
        raise RuntimeError(f"pip install kokoro soundfile  ({exc})") from exc
    print(f"[TTS] loading Kokoro (lang={lang_code!r}) — first run downloads ~300 MB …", flush=True)
    _kokoro_pipeline = KPipeline(lang_code=lang_code)
    print("[TTS] Kokoro ready.", flush=True)
    return _kokoro_pipeline


def _synth_kokoro(text: str, voice: str) -> tuple[str, str] | None:
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        print(f"[TTS] kokoro needs soundfile: pip install soundfile  ({exc})", flush=True)
        return None

    try:
        # 'b' = British phonemes (bf_* voices), 'a' = American (af_* voices)
        lang_code = "b" if voice.startswith("b") else "a"
        pipeline = _load_kokoro(lang_code)
        audio_chunks = [audio for _, _, audio in pipeline(text, voice=voice, speed=1.0)]
        if not audio_chunks:
            print("[TTS] Kokoro returned no audio", flush=True)
            return None
        audio = np.concatenate(audio_chunks)
    except Exception as exc:
        print(f"[TTS] Kokoro synthesis failed: {exc}", flush=True)
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        tmp_path = fh.name
    try:
        sf.write(tmp_path, audio, 24000)
    except Exception as exc:
        print(f"[TTS] wav write failed: {exc}", flush=True)
        Path(tmp_path).unlink(missing_ok=True)
        return None

    return tmp_path, "waveaudio"


# ── Chatterbox Turbo backend ────────────────────────────────────────────────

def _load_chatterbox(device: str):
    global _chatterbox_model
    if _chatterbox_model is not None:
        return _chatterbox_model
    try:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
    except ImportError as exc:
        raise RuntimeError(f"pip install chatterbox-tts  ({exc})") from exc
    print(f"[TTS] loading Chatterbox (device={device!r}) …", flush=True)
    try:
        _chatterbox_model = ChatterboxTurboTTS.from_pretrained(device=device)
    except Exception as exc:
        if device != "cpu":
            print(f"[TTS] Chatterbox {device} init failed ({exc}) — retrying on cpu", flush=True)
            _chatterbox_model = ChatterboxTurboTTS.from_pretrained(device="cpu")
        else:
            raise
    print("[TTS] Chatterbox ready.", flush=True)
    return _chatterbox_model


def _synth_chatterbox(text: str, device: str) -> tuple[str, str] | None:
    try:
        model = _load_chatterbox(device)
        wav = model.generate(text)
    except Exception as exc:
        print(f"[TTS] Chatterbox synthesis failed: {exc}", flush=True)
        return None

    try:
        import torchaudio as ta
    except ImportError as exc:
        print(f"[TTS] chatterbox needs torchaudio: pip install torchaudio  ({exc})", flush=True)
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        tmp_path = fh.name
    try:
        ta.save(tmp_path, wav, model.sr)
    except Exception as exc:
        print(f"[TTS] wav write failed: {exc}", flush=True)
        Path(tmp_path).unlink(missing_ok=True)
        return None

    return tmp_path, "waveaudio"


# ── Shared MCI playback ───────────────────────────────────────────────────────

def _mci_play(tmp_path: str, file_type: str, text: str, on_done=None) -> None:
    """Open file with MCI, play to completion, then clean up. Single-shot path
    (speak()): owns the speaking flag for its whole duration."""
    global _current_alias
    alias = f"vesper_{random.randint(0, 999_999)}"
    with _playback_lock:
        try:
            _mci(f'open "{tmp_path}" type {file_type} alias {alias}')
            with _alias_lock:
                _current_alias = alias
            _broadcast_viseme(alias, text)
            speaking.set()
            _mci(f"play {alias} wait")
        finally:
            speaking.clear()
            with _alias_lock:
                _current_alias = None
            try:
                _mci(f"close {alias}")
            except Exception:
                pass
            Path(tmp_path).unlink(missing_ok=True)
            if on_done:
                on_done()


def _utt_play(tmp_path: str, file_type: str, text: str) -> None:
    """Play one utterance segment. Sets `speaking` but does NOT clear it —
    the utterance play loop clears it once the whole utterance is done, so
    the clap detector stays muted through inter-sentence gaps."""
    global _current_alias
    alias = f"vesper_{random.randint(0, 999_999)}"
    try:
        _mci(f'open "{tmp_path}" type {file_type} alias {alias}')
        with _alias_lock:
            _current_alias = alias
        _broadcast_viseme(alias, text)
        speaking.set()
        _mci(f"play {alias} wait")
    finally:
        with _alias_lock:
            _current_alias = None
        try:
            _mci(f"close {alias}")
        except Exception:
            pass
        Path(tmp_path).unlink(missing_ok=True)


def _mci(cmd: str) -> None:
    ctypes.WinDLL("winmm.dll").mciSendStringW(cmd, None, 0, None)


def _mci_query(cmd: str) -> str:
    buf = ctypes.create_unicode_buffer(128)
    ctypes.WinDLL("winmm.dll").mciSendStringW(cmd, buf, 128, None)
    return buf.value


def _broadcast_viseme(alias: str, text: str) -> None:
    """Query the just-opened clip's duration from MCI and broadcast a
    synthetic envelope timed to it. Best-effort: never raises, never blocks
    playback -- matches this module's existing fire-and-forget UI pattern."""
    try:
        dur_ms = int(_mci_query(f"status {alias} length"))
    except Exception:
        return
    if dur_ms <= 0:
        return
    try:
        from voice import ui_server
        ui_server.post_event({
            "type": "viseme",
            "envelope": _estimate_envelope(text, dur_ms / 1000.0),
            "interval_ms": 40,
            "duration_ms": dur_ms,
        })
    except Exception:
        pass
