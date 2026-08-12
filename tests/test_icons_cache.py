"""voice/tools/icons.py::get_icon_png -- resolve+extract+disk-cache pipeline.
resolve_exe_path/extract_icon_png are mocked; get_data_dir() is redirected
to tmp_path so this never touches the real %APPDATA%\\Vesper cache."""
from __future__ import annotations

from voice import config as cfg
from voice.tools import icons


def test_extracts_and_caches_on_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(icons, "resolve_exe_path", lambda t: r"C:\apps\zoom.exe")
    calls = []

    def fake_extract(path):
        calls.append(path)
        return b"PNGDATA"

    monkeypatch.setattr(icons, "extract_icon_png", fake_extract)
    result = icons.get_icon_png("zoom.exe")
    assert result == b"PNGDATA"
    assert calls == [r"C:\apps\zoom.exe"]
    cached = list((tmp_path / "icon_cache").glob("*.png"))
    assert len(cached) == 1
    assert cached[0].read_bytes() == b"PNGDATA"


def test_second_call_serves_from_cache_without_re_extracting(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(icons, "resolve_exe_path", lambda t: r"C:\apps\zoom.exe")
    calls = []
    monkeypatch.setattr(icons, "extract_icon_png", lambda path: calls.append(path) or b"PNGDATA")

    icons.get_icon_png("zoom.exe")
    icons.get_icon_png("zoom.exe")
    assert len(calls) == 1  # second call hit the cache


def test_unresolvable_target_returns_none_without_caching(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(icons, "resolve_exe_path", lambda t: None)
    result = icons.get_icon_png("spotify:")
    assert result is None
    cache_dir = tmp_path / "icon_cache"
    assert not cache_dir.exists() or list(cache_dir.glob("*.png")) == []


def test_extraction_failure_returns_none_without_caching(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(icons, "resolve_exe_path", lambda t: r"C:\apps\broken.exe")
    monkeypatch.setattr(icons, "extract_icon_png", lambda path: None)
    result = icons.get_icon_png("broken.exe")
    assert result is None
    cache_dir = tmp_path / "icon_cache"
    assert not cache_dir.exists() or list(cache_dir.glob("*.png")) == []
