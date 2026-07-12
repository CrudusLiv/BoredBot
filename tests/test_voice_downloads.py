import os
import time
from pathlib import Path

import pytest

from voice import config as cfg
from voice import downloads
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat


def test_config_has_downloads_defaults():
    # Assert on DEFAULTS, not load(): load() merges the user's installed
    # config, where these toggles may legitimately differ.
    conf = cfg.DEFAULTS
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


def test_is_under_true(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    assert downloads.is_under(str(f), [str(tmp_path)]) is True


def test_is_under_false(tmp_path):
    assert downloads.is_under("C:/Windows/system32/x.dll", [str(tmp_path)]) is False


def test_file_candidate_moves_into_inbox(tmp_path):
    watch = tmp_path / "dl"; watch.mkdir()
    inbox = tmp_path / "inbox"; inbox.mkdir()
    src = watch / "lecture.pdf"; src.write_bytes(b"hi")
    res = downloads.file_candidate(str(src), [str(watch)], inbox)
    assert res["ok"] is True
    assert (inbox / "lecture.pdf").read_bytes() == b"hi"
    assert not src.exists()


def test_file_candidate_rejects_outside_watch(tmp_path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    outside = tmp_path / "elsewhere" / "x.pdf"
    outside.parent.mkdir(); outside.write_bytes(b"x")
    res = downloads.file_candidate(str(outside), [str(tmp_path / "dl")], inbox)
    assert res["ok"] is False
    assert outside.exists()          # not moved


def test_file_candidate_decollides_name(tmp_path):
    watch = tmp_path / "dl"; watch.mkdir()
    inbox = tmp_path / "inbox"; inbox.mkdir()
    (inbox / "a.pdf").write_bytes(b"old")
    src = watch / "a.pdf"; src.write_bytes(b"new")
    res = downloads.file_candidate(str(src), [str(watch)], inbox)
    assert res["ok"] is True
    assert (inbox / "a (2).pdf").read_bytes() == b"new"
    assert (inbox / "a.pdf").read_bytes() == b"old"


def test_file_candidate_missing_source(tmp_path):
    watch = tmp_path / "dl"; watch.mkdir()
    inbox = tmp_path / "inbox"; inbox.mkdir()
    res = downloads.file_candidate(str(watch / "gone.pdf"), [str(watch)], inbox)
    assert res["ok"] is False


def test_file_candidate_moves_resolved_target_not_out_of_folder_link(tmp_path):
    # Guard against the resolved-vs-raw inconsistency: is_under() validates
    # the RESOLVED path, so a symlink object that lives OUTSIDE the watch
    # folder but whose target resolves INSIDE it passes the guard. The fix
    # must then act on that same resolved (in-folder) target consistently —
    # never on the raw out-of-folder link object. So the real target file
    # gets consumed/moved, while the link object itself (outside the watch
    # folder) is left exactly where it was, untouched.
    watch = tmp_path / "dl"; watch.mkdir()
    inbox = tmp_path / "inbox"; inbox.mkdir()
    outside = tmp_path / "elsewhere"; outside.mkdir()
    target = watch / "real.pdf"; target.write_bytes(b"secret")
    link = outside / "link.pdf"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform/privilege level")

    res = downloads.file_candidate(str(link), [str(watch)], inbox)

    assert res["ok"] is True
    assert (inbox / "real.pdf").read_bytes() == b"secret"   # resolved target moved
    assert not target.exists()                              # ...and gone from watch
    assert os.path.lexists(link)                             # link object itself, outside
                                                              # the watch folder, was never
                                                              # moved/consumed by the action
    assert not (inbox / "link.pdf").exists()


DL_CONF = {
    "timezone_offset_hours": 8,
    "downloads_triage_enabled": True,
    "downloads_watch_folders": [],       # set per-test
    "downloads_watch_exts": [".pdf"],
}


@pytest.fixture
def dl_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: tmp_path)   # non-None => filing allowed
    posts: list[dict] = []
    monkeypatch.setattr(hb_mod, "_post",
                        lambda text, level="INFO", meta=None: posts.append({"text": text, "meta": meta}))
    return posts


def _hb() -> Heartbeat:
    return Heartbeat(interval_minutes=30, idle_fn=lambda: None)


def test_check_downloads_disabled_no_posts(dl_env, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(DL_CONF, downloads_triage_enabled=False))
    _hb()._check_downloads()
    assert dl_env == []


def test_check_downloads_posts_suggestion(dl_env, tmp_path, monkeypatch):
    dl = tmp_path / "dl"; dl.mkdir()
    f = dl / "lecture.pdf"; f.write_bytes(b"x")
    import os; os.utime(f, (100.0, 100.0))
    monkeypatch.setattr(cfg, "load", lambda: dict(DL_CONF, downloads_watch_folders=[str(dl)]))
    _hb()._check_downloads()
    assert len(dl_env) == 1
    assert "lecture.pdf" in dl_env[0]["text"]
    assert dl_env[0]["meta"]["kind"] == "download_suggestion"
    assert dl_env[0]["meta"]["path"] == str(f)


def test_check_downloads_dedups_second_tick(dl_env, tmp_path, monkeypatch):
    dl = tmp_path / "dl"; dl.mkdir()
    f = dl / "lecture.pdf"; f.write_bytes(b"x")
    import os; os.utime(f, (100.0, 100.0))
    monkeypatch.setattr(cfg, "load", lambda: dict(DL_CONF, downloads_watch_folders=[str(dl)]))
    hb = _hb()
    hb._check_downloads(); hb._check_downloads()
    assert len(dl_env) == 1          # second tick: already seen


def test_check_downloads_survives_scan_error(dl_env, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(DL_CONF, downloads_watch_folders=[str(tmp_path)]))
    from voice import downloads
    monkeypatch.setattr(downloads, "scan_new", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _hb()._check_downloads()         # must not raise
    assert dl_env == []


from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from voice import ui_server
    dl = tmp_path / "dl"; dl.mkdir()
    vault = tmp_path / "vault"; (vault / "inbox").mkdir(parents=True)
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: vault)
    monkeypatch.setattr(cfg, "load",
                        lambda: dict(DL_CONF, downloads_watch_folders=[str(dl)]))
    monkeypatch.setattr(ui_server, "TOKEN", "t")
    return TestClient(ui_server.app), dl, vault


def test_file_endpoint_moves(client):
    c, dl, vault = client
    src = dl / "a.pdf"; src.write_bytes(b"x")
    r = c.post("/cmd/downloads/file", json={"path": str(src)}, headers={"X-Vesper-Token": "t"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (vault / "inbox" / "a.pdf").exists()


def test_file_endpoint_rejects_outside(client):
    c, dl, vault = client
    outside = vault / "secret.pdf"; outside.write_bytes(b"x")   # not under watch folder
    r = c.post("/cmd/downloads/file", json={"path": str(outside)}, headers={"X-Vesper-Token": "t"})
    assert r.status_code == 400
    assert outside.exists()


def test_file_endpoint_requires_token(client):
    c, dl, vault = client
    r = c.post("/cmd/downloads/file", json={"path": str(dl / "a.pdf")})
    assert r.status_code == 401


def test_dismiss_endpoint_marks_seen(client):
    c, dl, vault = client
    src = dl / "a.pdf"; src.write_bytes(b"x")
    import os; os.utime(src, (100.0, 100.0))
    r = c.post("/cmd/downloads/dismiss", json={"path": str(src)}, headers={"X-Vesper-Token": "t"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert downloads.load_seen(vault.parent).get(str(src)) == 100.0
    assert src.exists()              # dismiss never moves
