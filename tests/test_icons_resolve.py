"""voice/tools/icons.py::resolve_exe_path -- maps a PC-control target or
activity-awareness exe name to a real .exe path. pc_control.discover_apps()
is mocked; no real Start Menu scan happens."""
from __future__ import annotations

from voice.tools import icons, pc_control


def test_full_existing_exe_path_returned_as_is(tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"")
    assert icons.resolve_exe_path(str(exe)) == str(exe)


def test_full_exe_path_that_does_not_exist_returns_none(tmp_path):
    missing = tmp_path / "gone.exe"
    assert icons.resolve_exe_path(str(missing)) is None


def test_non_exe_path_returns_none(tmp_path):
    doc = tmp_path / "readme.txt"
    doc.write_text("")
    assert icons.resolve_exe_path(str(doc)) is None


def test_empty_target_returns_none():
    assert icons.resolve_exe_path("") is None
    assert icons.resolve_exe_path("   ") is None


def test_uri_target_returns_none(monkeypatch):
    monkeypatch.setattr(pc_control, "discover_apps", lambda: [])
    assert icons.resolve_exe_path("spotify:") is None


def test_bare_exe_name_matched_against_discovered_apps(monkeypatch):
    monkeypatch.setattr(pc_control, "discover_apps",
                         lambda: [{"name": "zoom", "target": r"C:\Users\x\Zoom\Zoom.exe"}])
    assert icons.resolve_exe_path("zoom.exe") == r"C:\Users\x\Zoom\Zoom.exe"


def test_bare_name_without_extension_matched(monkeypatch):
    monkeypatch.setattr(pc_control, "discover_apps",
                         lambda: [{"name": "zoom", "target": r"C:\Users\x\Zoom\Zoom.exe"}])
    assert icons.resolve_exe_path("zoom") == r"C:\Users\x\Zoom\Zoom.exe"


def test_bare_name_matched_case_insensitively(monkeypatch):
    monkeypatch.setattr(pc_control, "discover_apps",
                         lambda: [{"name": "zoom", "target": r"C:\Users\x\Zoom\ZOOM.EXE"}])
    assert icons.resolve_exe_path("zoom.exe") == r"C:\Users\x\Zoom\ZOOM.EXE"


def test_bare_name_with_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(pc_control, "discover_apps", lambda: [])
    assert icons.resolve_exe_path("nonexistent.exe") is None
