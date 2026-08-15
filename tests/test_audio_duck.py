"""voice/audio_duck.py -- duck()/restore() logic, mocked at the pycaw
boundary (AudioUtilities.GetAllSessions) so no real Windows audio session
is touched. Verifies: opt-in gating, own-process exclusion, proportional
scaling, idempotency, and best-effort failure handling."""
from __future__ import annotations

import sys
import types

import pytest

from voice import audio_duck as duck_mod
from voice import config as cfg


class _FakeVolume:
    def __init__(self, level: float) -> None:
        self.level = level
        self.set_calls: list[float] = []

    def GetMasterVolume(self) -> float:
        return self.level

    def SetMasterVolume(self, level: float, _guid) -> None:
        self.set_calls.append(level)
        self.level = level


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _FakeSession:
    def __init__(self, pid: int | None, level: float) -> None:
        self.Process = _FakeProcess(pid) if pid is not None else None
        self.SimpleAudioVolume = _FakeVolume(level)


@pytest.fixture(autouse=True)
def _reset_state():
    duck_mod._ducked.clear()
    yield
    duck_mod._ducked.clear()


def _install_fake_pycaw(monkeypatch, sessions):
    fake_pycaw_pkg = types.ModuleType("pycaw")
    fake_pycaw_mod = types.ModuleType("pycaw.pycaw")
    fake_pycaw_mod.AudioUtilities = types.SimpleNamespace(GetAllSessions=lambda: sessions)
    monkeypatch.setitem(sys.modules, "pycaw", fake_pycaw_pkg)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", fake_pycaw_mod)


def _conf(monkeypatch, **overrides):
    base = {"audio_duck_enabled": True, "audio_duck_percent": 25}
    base.update(overrides)
    monkeypatch.setattr(cfg, "load", lambda: base)


def test_duck_noop_when_disabled(monkeypatch):
    _conf(monkeypatch, audio_duck_enabled=False)
    other = _FakeSession(pid=999, level=1.0)
    _install_fake_pycaw(monkeypatch, [other])

    duck_mod.duck()

    assert other.SimpleAudioVolume.set_calls == []
    assert duck_mod._ducked == {}


def test_duck_noop_when_pycaw_missing(monkeypatch):
    _conf(monkeypatch)
    monkeypatch.setitem(sys.modules, "pycaw", None)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", None)

    duck_mod.duck()  # must not raise

    assert duck_mod._ducked == {}


def test_duck_scales_other_sessions_proportionally(monkeypatch):
    _conf(monkeypatch, audio_duck_percent=25)
    other = _FakeSession(pid=999, level=0.8)
    _install_fake_pycaw(monkeypatch, [other])

    duck_mod.duck()

    assert other.SimpleAudioVolume.set_calls == [pytest.approx(0.2)]


def test_duck_skips_own_process(monkeypatch):
    _conf(monkeypatch)
    monkeypatch.setattr(duck_mod.os, "getpid", lambda: 4242)
    own = _FakeSession(pid=4242, level=1.0)
    other = _FakeSession(pid=999, level=1.0)
    _install_fake_pycaw(monkeypatch, [own, other])

    duck_mod.duck()

    assert own.SimpleAudioVolume.set_calls == []
    assert other.SimpleAudioVolume.set_calls == [pytest.approx(0.25)]


def test_duck_skips_sessions_with_no_process(monkeypatch):
    _conf(monkeypatch)
    system_sounds = _FakeSession(pid=None, level=1.0)
    _install_fake_pycaw(monkeypatch, [system_sounds])

    duck_mod.duck()  # must not raise

    assert system_sounds.SimpleAudioVolume.set_calls == []


def test_duck_is_idempotent(monkeypatch):
    _conf(monkeypatch)
    other = _FakeSession(pid=999, level=1.0)
    _install_fake_pycaw(monkeypatch, [other])

    duck_mod.duck()
    duck_mod.duck()  # second call while already ducked -- no re-duck

    assert other.SimpleAudioVolume.set_calls == [pytest.approx(0.25)]


def test_restore_puts_back_original_volume(monkeypatch):
    _conf(monkeypatch)
    other = _FakeSession(pid=999, level=0.6)
    _install_fake_pycaw(monkeypatch, [other])

    duck_mod.duck()
    duck_mod.restore()

    assert other.SimpleAudioVolume.level == pytest.approx(0.6)
    assert duck_mod._ducked == {}


def test_restore_noop_when_nothing_ducked(monkeypatch):
    duck_mod.restore()  # must not raise
    assert duck_mod._ducked == {}


def test_restore_survives_a_vanished_session(monkeypatch):
    _conf(monkeypatch)
    other = _FakeSession(pid=999, level=1.0)
    _install_fake_pycaw(monkeypatch, [other])
    duck_mod.duck()

    def _raise(_level, _guid):
        raise OSError("session gone")

    other.SimpleAudioVolume.SetMasterVolume = _raise

    duck_mod.restore()  # must not raise

    assert duck_mod._ducked == {}
