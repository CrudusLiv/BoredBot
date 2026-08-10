# tests/test_voice_tts_chatterbox.py
"""Tests for the Chatterbox Turbo TTS backend in voice/tts.py.

No real model/GPU involved: _load_chatterbox's import of chatterbox.tts_turbo
is exercised either against a None sys.modules entry (forcing a real
ImportError, proving the helpful-error path regardless of whether the
package is actually installed) or against a fake module injected into
sys.modules (proving the cuda->cpu retry path). _synth()'s dispatch/fallback
contract is tested by monkeypatching _synth_chatterbox itself, the same way
_synth_edge and _synth_kokoro are never exercised for real in this suite."""
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

    def fake_synth_chatterbox(text, device, voice_path):
        calls.append((text, device, voice_path))
        return ("/tmp/fake.wav", "waveaudio")

    monkeypatch.setattr(tts_mod, "_synth_chatterbox", fake_synth_chatterbox)

    result = tts_mod._synth("hello there")

    assert calls == [("hello there", "cuda", "")]
    assert result == ("/tmp/fake.wav", "waveaudio")


def test_synth_passes_configured_voice_path_to_chatterbox(monkeypatch):
    monkeypatch.setattr(
        "voice.config.load",
        lambda: {
            "tts_engine": "chatterbox",
            "tts_chatterbox_device": "cuda",
            "tts_chatterbox_voice_path": r"C:\voice_ref.wav",
        },
    )
    calls = []

    def fake_synth_chatterbox(text, device, voice_path):
        calls.append((text, device, voice_path))
        return ("/tmp/fake.wav", "waveaudio")

    monkeypatch.setattr(tts_mod, "_synth_chatterbox", fake_synth_chatterbox)

    tts_mod._synth("hello there")

    assert calls == [("hello there", "cuda", r"C:\voice_ref.wav")]


def test_synth_falls_back_to_edge_when_chatterbox_returns_none(monkeypatch):
    monkeypatch.setattr(
        "voice.config.load",
        lambda: {"tts_engine": "chatterbox", "tts_chatterbox_device": "cuda"},
    )
    monkeypatch.setattr(tts_mod, "_synth_chatterbox", lambda text, device, voice_path: None)

    edge_calls = []

    def fake_synth_edge(text, voice):
        edge_calls.append((text, voice))
        return ("/tmp/edge.mp3", "mpegvideo")

    monkeypatch.setattr(tts_mod, "_synth_edge", fake_synth_edge)

    result = tts_mod._synth("hi")

    assert edge_calls == [("hi", "en-GB-SoniaNeural")]
    assert result == ("/tmp/edge.mp3", "mpegvideo")


def test_synth_chatterbox_prepares_voice_once_when_path_configured(monkeypatch):
    monkeypatch.setattr(tts_mod, "_chatterbox_voice_path", None)
    prepare_calls = []

    class _FakeModel:
        sr = 24000
        def prepare_conditionals(self, path, norm_loudness=True):
            prepare_calls.append(path)
        def generate(self, text):
            return "fake-wav"

    fake_model = _FakeModel()
    monkeypatch.setattr(tts_mod, "_load_chatterbox", lambda device: fake_model)
    monkeypatch.setattr(tts_mod, "_write_wav", lambda wav, sr: ("/tmp/fake.wav", "waveaudio"))

    tts_mod._synth_chatterbox("hi", "cpu", "/ref/voice.wav")
    tts_mod._synth_chatterbox("again", "cpu", "/ref/voice.wav")

    # Same path both calls — prepare_conditionals only runs once, not per-reply.
    assert prepare_calls == ["/ref/voice.wav"]


def test_synth_chatterbox_reprepares_voice_when_path_changes(monkeypatch):
    monkeypatch.setattr(tts_mod, "_chatterbox_voice_path", "/ref/old.wav")
    prepare_calls = []

    class _FakeModel:
        sr = 24000
        def prepare_conditionals(self, path, norm_loudness=True):
            prepare_calls.append(path)
        def generate(self, text):
            return "fake-wav"

    fake_model = _FakeModel()
    monkeypatch.setattr(tts_mod, "_load_chatterbox", lambda device: fake_model)
    monkeypatch.setattr(tts_mod, "_write_wav", lambda wav, sr: ("/tmp/fake.wav", "waveaudio"))

    tts_mod._synth_chatterbox("hi", "cpu", "/ref/new.wav")

    assert prepare_calls == ["/ref/new.wav"]


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
    # A None entry in sys.modules forces Python's import machinery to raise
    # ImportError, regardless of whether chatterbox-tts is actually
    # installed on this machine — more robust than deleting the entry,
    # which only works if the package is genuinely absent.
    monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", None)

    try:
        tts_mod._load_chatterbox("cuda")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "pip install chatterbox-tts" in str(exc)
