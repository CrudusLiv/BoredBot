"""voice/tools/launch_app.py::_run — optional per-entry cwd/args."""
from __future__ import annotations

import json

from voice.tools.launch_app import _run


def test_run_plain_string_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "voice.tools.launch_app.subprocess.Popen",
        lambda *a, **k: calls.append((a, k)),
    )
    result = json.loads(_run(["C:/apps/spotify.exe"]))
    assert result["status"] == "ok"
    assert calls  # Popen was invoked


def test_run_dict_entry_passes_cwd(monkeypatch):
    calls = []

    def _fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr("voice.tools.launch_app.subprocess.Popen", _fake_popen)
    result = json.loads(_run([{"path": "C:/apps/code.exe", "cwd": "D:/GitHub/Vesper", "args": []}]))
    assert result["status"] == "ok"
    assert calls[0][1].get("cwd") == "D:/GitHub/Vesper"


def test_run_dict_entry_appends_args(monkeypatch):
    calls = []

    def _fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr("voice.tools.launch_app.subprocess.Popen", _fake_popen)
    json.loads(_run([{"path": "C:/apps/code.exe", "cwd": None, "args": ["."]}]))
    assert calls[0][0] == ["C:/apps/code.exe", "."]
