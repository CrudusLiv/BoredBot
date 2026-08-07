"""profiles.set_app_state + the update_profile_app_state voice tool."""
from __future__ import annotations

import json

import pytest

from voice import config as cfg
from voice import profiles


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)


def _approve(monkeypatch, *aliases):
    from voice import approved_apps
    monkeypatch.setattr(approved_apps, "get_approved", lambda: {a: f"C:/apps/{a}.exe" for a in aliases})


def test_set_app_state_updates_matching_entry(monkeypatch):
    _approve(monkeypatch, "vscode")
    profiles.create("study", "Study Mode", ["vscode"])
    profiles.set_app_state("Study Mode", "vscode", cwd="D:/GitHub/Vesper")
    stored = profiles.get("study")
    assert stored["apps"][0]["cwd"] == "D:/GitHub/Vesper"


def test_set_app_state_unknown_profile_raises(monkeypatch):
    _approve(monkeypatch, "vscode")
    with pytest.raises(KeyError):
        profiles.set_app_state("Nonexistent", "vscode", cwd="D:/x")


def test_set_app_state_unknown_alias_raises(monkeypatch):
    _approve(monkeypatch, "vscode")
    profiles.create("study", "Study Mode", ["vscode"])
    with pytest.raises(KeyError, match="spotify"):
        profiles.set_app_state("Study Mode", "spotify", cwd="D:/x")


def test_tool_wrapper_returns_json(monkeypatch):
    from voice.tools.profile_state import update_profile_app_state
    _approve(monkeypatch, "vscode")
    profiles.create("study", "Study Mode", ["vscode"])
    result = json.loads(update_profile_app_state("Study Mode", "vscode", cwd="D:/GitHub/Vesper"))
    assert result["status"] == "ok"
    assert profiles.get("study")["apps"][0]["cwd"] == "D:/GitHub/Vesper"


def test_tool_registered_in_dispatch():
    from voice.tools import REGISTRY, dispatch
    assert any(t["name"] == "update_profile_app_state" for t in REGISTRY)
