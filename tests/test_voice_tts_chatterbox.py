# tests/test_voice_tts_chatterbox.py
"""Tests for the Chatterbox Turbo TTS backend in voice/tts.py.

No real model/GPU involved: _load_chatterbox's import of chatterbox.tts_turbo
is exercised either against the genuinely-absent package (proving the
helpful-error path) or against a fake module injected into sys.modules
(proving the cuda->cpu retry path). _synth()'s dispatch/fallback contract is
tested by monkeypatching _synth_chatterbox itself, the same way _synth_edge
and _synth_kokoro are never exercised for real in this suite."""
from __future__ import annotations

import sys
import types

import voice.tts as tts_mod


def test_synth_dispatches_to_chatterbox_when_configured(monkeypatch):
    monkeypatch.setattr(
        "voice.config.load",
        lambda: {"tts_engine": "chatterbox", "tts_chatterbox_device": "cuda"},
    )
    calls = []

    def fake_synth_chatterbox(text, device):
        calls.append((text, device))
        return ("/tmp/fake.wav", "waveaudio")

    monkeypatch.setattr(tts_mod, "_synth_chatterbox", fake_synth_chatterbox)

    result = tts_mod._synth("hello there")

    assert calls == [("hello there", "cuda")]
    assert result == ("/tmp/fake.wav", "waveaudio")


def test_synth_falls_back_to_edge_when_chatterbox_returns_none(monkeypatch):
    monkeypatch.setattr(
        "voice.config.load",
        lambda: {"tts_engine": "chatterbox", "tts_chatterbox_device": "cuda"},
    )
    monkeypatch.setattr(tts_mod, "_synth_chatterbox", lambda text, device: None)

    edge_calls = []

    def fake_synth_edge(text, voice):
        edge_calls.append((text, voice))
        return ("/tmp/edge.mp3", "mpegvideo")

    monkeypatch.setattr(tts_mod, "_synth_edge", fake_synth_edge)

    result = tts_mod._synth("hi")

    assert edge_calls == [("hi", "en-GB-SoniaNeural")]
    assert result == ("/tmp/edge.mp3", "mpegvideo")


def test_load_chatterbox_retries_on_cpu_when_cuda_init_fails(monkeypatch):
    monkeypatch.setattr(tts_mod, "_chatterbox_model", None)

    class _FakeChatterboxTurboTTS:
        @classmethod
        def from_pretrained(cls, device):
            if device == "cuda":
                raise RuntimeError("no CUDA device available")
            return "cpu-model-sentinel"

    fake_pkg = types.ModuleType("chatterbox")
    fake_submodule = types.ModuleType("chatterbox.tts_turbo")
    fake_submodule.ChatterboxTurboTTS = _FakeChatterboxTurboTTS
    monkeypatch.setitem(sys.modules, "chatterbox", fake_pkg)
    monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", fake_submodule)

    model = tts_mod._load_chatterbox("cuda")

    assert model == "cpu-model-sentinel"


def test_load_chatterbox_raises_helpful_error_when_package_missing(monkeypatch):
    monkeypatch.setattr(tts_mod, "_chatterbox_model", None)
    monkeypatch.delitem(sys.modules, "chatterbox", raising=False)
    monkeypatch.delitem(sys.modules, "chatterbox.tts_turbo", raising=False)

    try:
        tts_mod._load_chatterbox("cuda")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "pip install chatterbox-tts" in str(exc)
