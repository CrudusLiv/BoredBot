"""voice/stt.py::transcribe — audit-log instrumentation (duration + word rate).
Real faster-whisper inference is not exercised here; _load_model() is
replaced with a fake so this stays a fast, offline unit test."""
from __future__ import annotations

import io
import json
import wave

import pytest

from voice import config as cfg
from voice import stt


def _wav_bytes(n_samples: int, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return buf.getvalue()


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, audio, **kwargs):
        return self._segments, None


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: {})
    return tmp_path / "voice_audit.jsonl"


def test_transcribe_logs_duration_and_word_rate(env, monkeypatch):
    monkeypatch.setattr(stt, "_load_model", lambda: _FakeModel([_FakeSegment("hello there friend")]))
    audio_bytes = _wav_bytes(n_samples=16000 * 2)  # 2 seconds at 16kHz

    result = stt.transcribe(audio_bytes)

    assert result == "hello there friend"
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert entry["role"] == "stt"
    assert entry["content"] == "hello there friend"
    assert entry["meta"]["duration_s"] == 2.0
    assert entry["meta"]["word_count"] == 3
    assert entry["meta"]["words_per_second"] == 1.5


def test_transcribe_zero_duration_does_not_divide_by_zero(env, monkeypatch):
    monkeypatch.setattr(stt, "_load_model", lambda: _FakeModel([_FakeSegment("hi")]))
    audio_bytes = _wav_bytes(n_samples=0)

    result = stt.transcribe(audio_bytes)

    assert result == "hi"
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert entry["meta"]["duration_s"] == 0.0
    assert entry["meta"]["words_per_second"] == 0.0


def test_transcribe_empty_result_still_logs(env, monkeypatch):
    monkeypatch.setattr(stt, "_load_model", lambda: _FakeModel([]))
    audio_bytes = _wav_bytes(n_samples=16000)  # 1 second, model returns nothing

    result = stt.transcribe(audio_bytes)

    assert result == ""
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert entry["content"] == ""
    assert entry["meta"]["word_count"] == 0
    assert entry["meta"]["words_per_second"] == 0.0
