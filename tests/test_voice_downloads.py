import time
from pathlib import Path

from voice import config as cfg
from voice import downloads


def test_config_has_downloads_defaults():
    conf = cfg.load()
    assert conf["downloads_triage_enabled"] is False
    assert conf["downloads_watch_folders"] == []
    assert ".pdf" in conf["downloads_watch_exts"]
    assert ".pptx" in conf["downloads_watch_exts"]


def _mk(p: Path, mtime: float | None = None):
    p.write_bytes(b"x")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))


def test_scan_new_picks_allowed_ext(tmp_path):
    _mk(tmp_path / "lecture.pdf", mtime=100.0)
    out = downloads.scan_new([str(tmp_path)], [".pdf"], seen={}, min_age_seconds=0, now=1000.0)
    assert [c["name"] for c in out] == ["lecture.pdf"]
    assert out[0]["mtime"] == 100.0
    assert out[0]["dest"] == "inbox"


def test_scan_new_skips_wrong_ext(tmp_path):
    _mk(tmp_path / "installer.exe", mtime=100.0)
    out = downloads.scan_new([str(tmp_path)], [".pdf"], seen={}, min_age_seconds=0, now=1000.0)
    assert out == []


def test_scan_new_skips_partial_downloads(tmp_path):
    _mk(tmp_path / "big.pdf.crdownload", mtime=100.0)
    _mk(tmp_path / "big.part", mtime=100.0)
    out = downloads.scan_new([str(tmp_path)], [".pdf", ".part"], seen={}, min_age_seconds=0, now=1000.0)
    assert out == []


def test_scan_new_skips_too_new(tmp_path):
    _mk(tmp_path / "fresh.pdf", mtime=995.0)   # 5s old, min_age 20 => skip
    out = downloads.scan_new([str(tmp_path)], [".pdf"], seen={}, min_age_seconds=20, now=1000.0)
    assert out == []


def test_scan_new_dedups_seen(tmp_path):
    _mk(tmp_path / "seen.pdf", mtime=100.0)
    seen = {str(tmp_path / "seen.pdf"): 100.0}
    out = downloads.scan_new([str(tmp_path)], [".pdf"], seen=seen, min_age_seconds=0, now=1000.0)
    assert out == []


def test_scan_new_resurfaces_changed_mtime(tmp_path):
    _mk(tmp_path / "seen.pdf", mtime=200.0)
    seen = {str(tmp_path / "seen.pdf"): 100.0}   # old mtime => file replaced
    out = downloads.scan_new([str(tmp_path)], [".pdf"], seen=seen, min_age_seconds=0, now=1000.0)
    assert len(out) == 1


def test_scan_new_missing_folder_ignored(tmp_path):
    out = downloads.scan_new([str(tmp_path / "nope")], [".pdf"], seen={}, min_age_seconds=0, now=1000.0)
    assert out == []


def test_seen_roundtrip(tmp_path):
    downloads.mark_seen(tmp_path, "C:/D/a.pdf", 100.0)
    downloads.mark_seen(tmp_path, "C:/D/b.pdf", 200.0)
    seen = downloads.load_seen(tmp_path)
    assert seen == {"C:/D/a.pdf": 100.0, "C:/D/b.pdf": 200.0}


def test_load_seen_missing_returns_empty(tmp_path):
    assert downloads.load_seen(tmp_path) == {}


def test_load_seen_corrupt_returns_empty(tmp_path):
    (tmp_path / downloads.SEEN_FILE).write_text("{not json", encoding="utf-8")
    assert downloads.load_seen(tmp_path) == {}
