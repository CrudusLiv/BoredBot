"""voice/tools/pc_control.py::discover_apps -- Start Menu shortcut scan for
the settings UI's app-name autocomplete. win32com's WScript.Shell is
isolated behind _resolve_shortcut and mocked here; no real shortcuts are
read and no COM object is created."""
from __future__ import annotations

from voice.tools import pc_control


def test_discovers_exe_targets_from_lnk_files(tmp_path, monkeypatch):
    (tmp_path / "Notepad.lnk").write_text("")
    (tmp_path / "Spotify.lnk").write_text("")
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [tmp_path])
    targets = {"notepad.lnk": r"C:\Windows\notepad.exe", "spotify.lnk": r"C:\Users\x\Spotify.exe"}
    monkeypatch.setattr(pc_control, "_resolve_shortcut", lambda p: targets[p.name.lower()])
    result = pc_control.discover_apps()
    names = {a["name"] for a in result}
    assert names == {"notepad", "spotify"}


def test_skips_shortcuts_with_no_target(tmp_path, monkeypatch):
    (tmp_path / "Broken.lnk").write_text("")
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [tmp_path])
    monkeypatch.setattr(pc_control, "_resolve_shortcut", lambda p: "")
    assert pc_control.discover_apps() == []


def test_skips_non_exe_targets(tmp_path, monkeypatch):
    (tmp_path / "Readme.lnk").write_text("")
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [tmp_path])
    monkeypatch.setattr(pc_control, "_resolve_shortcut", lambda p: r"C:\docs\readme.txt")
    assert pc_control.discover_apps() == []


def test_missing_directory_is_skipped_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [tmp_path / "does-not-exist"])
    assert pc_control.discover_apps() == []


def test_results_are_sorted_by_name(tmp_path, monkeypatch):
    (tmp_path / "Zoom.lnk").write_text("")
    (tmp_path / "Anki.lnk").write_text("")
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [tmp_path])
    targets = {"zoom.lnk": r"C:\zoom.exe", "anki.lnk": r"C:\anki.exe"}
    monkeypatch.setattr(pc_control, "_resolve_shortcut", lambda p: targets[p.name.lower()])
    result = pc_control.discover_apps()
    assert [a["name"] for a in result] == ["anki", "zoom"]


def test_dedupes_case_insensitively_across_dirs(tmp_path, monkeypatch):
    d1 = tmp_path / "d1"
    d1.mkdir()
    d2 = tmp_path / "d2"
    d2.mkdir()
    (d1 / "Chrome.lnk").write_text("")
    (d2 / "chrome.lnk").write_text("")
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [d1, d2])
    monkeypatch.setattr(pc_control, "_resolve_shortcut", lambda p: r"C:\chrome.exe")
    result = pc_control.discover_apps()
    assert len(result) == 1
    assert result[0]["name"] == "chrome"


def test_nested_subfolders_are_scanned(tmp_path, monkeypatch):
    sub = tmp_path / "Accessories"
    sub.mkdir()
    (sub / "Notepad.lnk").write_text("")
    monkeypatch.setattr(pc_control, "_start_menu_dirs", lambda: [tmp_path])
    monkeypatch.setattr(pc_control, "_resolve_shortcut", lambda p: r"C:\Windows\notepad.exe")
    result = pc_control.discover_apps()
    assert [a["name"] for a in result] == ["notepad"]
