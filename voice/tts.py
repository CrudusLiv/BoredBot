"""Text-to-speech — three backends selectable via config `tts_engine`.

edge (default): Microsoft Edge TTS — free, requires internet.
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
import tempfile
import threading
from pathlib import Path

_alias_lock = threading.Lock()
_current_alias: str | None = None

# Serializes MCI playback so a proactive speak() and an utterance can't overlap audibly
_playback_lock = threading.Lock()

# Set while audio is physically playing — wakeword/clap import this to suppress self-triggering
speaking = threading.Event()

_kokoro_pipeline = None

_active_utterance: "Utterance | None" = None
_utterance_lock = threading.Lock()


def speak(text: str, on_done=None) -> None:
    """Synthesise and play in a daemon thread (non-blocking).

    on_done: optional zero-arg callable fired after playback ends or fails.
             Pass _wakeword_ready.set here instead of calling it after speak().
    """
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
        self._play_q: "queue.Queue[tuple[str, str] | None]" = queue.Queue()
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
            self._play_q.put(item)
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
                path, mci_type = item
                with _playback_lock:
                    if self._cancelled.is_set():
                        Path(path).unlink(missing_ok=True)
                        return
                    _utt_play(path, mci_type)
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
    """Start a pipelined utterance, cancelling any previous one."""
    global _active_utterance
    with _utterance_lock:
        if _active_utterance is not None:
            _active_utterance.cancel()
        utt = Utterance(on_done)
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
    _mci_play(item[0], item[1], on_done)


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


# ── Shared MCI playback ───────────────────────────────────────────────────────

def _mci_play(tmp_path: str, file_type: str, on_done=None) -> None:
    """Open file with MCI, play to completion, then clean up. Single-shot path
    (speak()): owns the speaking flag for its whole duration."""
    global _current_alias
    alias = f"vesper_{random.randint(0, 999_999)}"
    with _playback_lock:
        try:
            _mci(f'open "{tmp_path}" type {file_type} alias {alias}')
            with _alias_lock:
                _current_alias = alias
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


def _utt_play(tmp_path: str, file_type: str) -> None:
    """Play one utterance segment. Sets `speaking` but does NOT clear it —
    the utterance play loop clears it once the whole utterance is done, so
    the wakeword stays muted through inter-sentence gaps."""
    global _current_alias
    alias = f"vesper_{random.randint(0, 999_999)}"
    try:
        _mci(f'open "{tmp_path}" type {file_type} alias {alias}')
        with _alias_lock:
            _current_alias = alias
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
