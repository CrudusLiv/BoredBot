"""voice/profiles.py — per-app cwd/args state on top of the flat apps list."""
from __future__ import annotations

import pytest

from voice import config as cfg
from voice import profiles


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)


def _approve(monkeypatch, *aliases):
    from voice import approved_apps
    monkeypatch.setattr(approved_apps, "get_approved", lambda: {a: f"C:/apps/{a}.exe" for a in aliases})


def test_plain_string_app_normalizes_to_dict(monkeypatch):
    _approve(monkeypatch, "vscode")
    profiles.create("study", "Study Mode", ["vscode"])
    stored = profiles.get("study")
    assert stored["apps"] == [{"alias": "vscode", "cwd": None, "args": []}]


def test_dict_app_entry_preserves_cwd_and_args(monkeypatch):
    _approve(monkeypatch, "vscode")
    profiles.create("study", "Study Mode", [{"alias": "vscode", "cwd": "D:/GitHub/Vesper", "args": ["."]}])
    stored = profiles.get("study")
    assert stored["apps"] == [{"alias": "vscode", "cwd": "D:/GitHub/Vesper", "args": ["."]}]


def test_unapproved_alias_still_rejected_in_dict_form(monkeypatch):
    _approve(monkeypatch, "vscode")
    with pytest.raises(ValueError, match="spotify"):
        profiles.create("study", "Study Mode", [{"alias": "spotify", "cwd": "D:/Music"}])


def test_normalize_app_entry_defaults():
    assert profiles._normalize_app_entry("vscode") == {"alias": "vscode", "cwd": None, "args": []}
    assert profiles._normalize_app_entry({"alias": "vscode"}) == {"alias": "vscode", "cwd": None, "args": []}


def test_activate_passes_cwd_to_launch(monkeypatch):
    _approve(monkeypatch, "vscode")
    profiles.create("study", "Study Mode", [{"alias": "vscode", "cwd": "D:/GitHub/Vesper", "args": []}])

    seen = {}

    def _fake_run(cmds):
        seen["cmds"] = cmds
        return '{"launched": ["ok"], "errors": []}'

    monkeypatch.setattr("voice.profiles.launch_app._run", _fake_run)
    profiles.activate("study")
    assert seen["cmds"] == [{"path": "C:/apps/vscode.exe", "cwd": "D:/GitHub/Vesper", "args": []}]
