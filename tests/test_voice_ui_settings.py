"""Tests for the /cmd/settings patch endpoint in voice/ui_server.py.

Focus: the activity-awareness controls surfaced in the Cfg tab must round-trip
through POST /cmd/settings — a boolean toggle (activity_awareness_enabled) and a
list value (silence_when_running). Both are gated by the _SETTINGS_ALLOWED
allowlist, so this pins that they're patchable and that a list value survives
save->load intact.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from voice import config as cfg
from voice import ui_server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with config writes redirected to an isolated temp file so the
    user's real %APPDATA%\\Vesper\\config.json is never touched."""
    store = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "_installed_config", lambda: store)
    # Neutralise the repo dev config so load() reflects only DEFAULTS + our saves.
    monkeypatch.setattr(cfg, "_DEV_CONFIG", tmp_path / "nonexistent-dev.json")
    return TestClient(ui_server.app)


def _hdr() -> dict[str, str]:
    return {"X-Vesper-Token": ui_server.TOKEN}


def test_patch_boolean_toggle_round_trips(client):
    r = client.post("/cmd/settings", headers=_hdr(),
                    json={"key": "activity_awareness_enabled", "value": True})
    assert r.status_code == 200, r.text
    got = client.get("/cmd/settings").json()
    assert got["activity_awareness_enabled"] is True


def test_patch_list_value_round_trips(client):
    procs = ["zoom.exe", "game.exe"]
    r = client.post("/cmd/settings", headers=_hdr(),
                    json={"key": "silence_when_running", "value": procs})
    assert r.status_code == 200, r.text
    got = client.get("/cmd/settings").json()
    assert got["silence_when_running"] == procs


def test_patch_rejects_unknown_key(client):
    r = client.post("/cmd/settings", headers=_hdr(),
                    json={"key": "not_a_real_setting", "value": 1})
    assert r.status_code == 400


def test_patch_dict_value_round_trips(client):
    apps = {"spotify": "spotify:", "notepad": "notepad.exe"}
    r = client.post("/cmd/settings", headers=_hdr(),
                    json={"key": "pc_control_apps", "value": apps})
    assert r.status_code == 200, r.text
    got = client.get("/cmd/settings").json()
    assert got["pc_control_apps"] == apps


@pytest.mark.parametrize("key,value", [
    ("ptt_key", "f6"),
    ("screen_read_capture_hotkey", "f9"),
    ("screen_read_ask_hotkey", "f10"),
    ("screen_read_copy_hotkey", "f11"),
    ("screen_read_dismiss_hotkey", "f12"),
])
def test_patch_keybind_round_trips(client, key, value):
    r = client.post("/cmd/settings", headers=_hdr(), json={"key": key, "value": value})
    assert r.status_code == 200, r.text
    got = client.get("/cmd/settings").json()
    assert got[key] == value


@pytest.mark.parametrize("key,value", [
    ("tts_chatterbox_device", "cpu"),
    ("tts_chatterbox_voice_path", "C:\\voice\\clip.wav"),
])
def test_patch_chatterbox_field_round_trips(client, key, value):
    r = client.post("/cmd/settings", headers=_hdr(), json={"key": key, "value": value})
    assert r.status_code == 200, r.text
    got = client.get("/cmd/settings").json()
    assert got[key] == value


def test_patch_screen_read_hotkey_can_be_unbound(client):
    r = client.post("/cmd/settings", headers=_hdr(),
                     json={"key": "screen_read_capture_hotkey", "value": ""})
    assert r.status_code == 200, r.text
    got = client.get("/cmd/settings").json()
    assert got["screen_read_capture_hotkey"] == ""
