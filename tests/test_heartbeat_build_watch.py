"""voice/heartbeat.py::_check_build_watch — daily local test + release CI check."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {
    "timezone_offset_hours": 8, "build_watch_enabled": True,
    "build_watch_time": "07:30", "build_watch_repo": "me/vesper",
}


def _env(tmp_path, monkeypatch, conf=None, hour=7, minute=35):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    fixed_now = datetime(2026, 7, 7, hour, minute, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(hb_mod, "datetime", type("F", (), {"now": staticmethod(lambda tz=None: fixed_now)}))
    posts = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def test_silent_when_tests_pass_and_workflow_ok(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.test_runner, "run_test_suite", lambda root: {"passed": 5, "failed": 0, "ok": True})
    monkeypatch.setattr(hb_mod.github_int, "latest_workflow_run", lambda repo, workflow_file="build.yml": {
        "status": "completed", "conclusion": "success", "html_url": "x", "created_at": "y"})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_build_watch()
    assert posts == []


def test_posts_when_local_tests_fail(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.test_runner, "run_test_suite", lambda root: {"passed": 4, "failed": 1, "ok": False})
    monkeypatch.setattr(hb_mod.github_int, "latest_workflow_run", lambda repo, workflow_file="build.yml": None)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_build_watch()
    assert any("1 test" in p and "fail" in p for p in posts)


def test_posts_when_release_workflow_failed(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.test_runner, "run_test_suite", lambda root: {"passed": 5, "failed": 0, "ok": True})
    monkeypatch.setattr(hb_mod.github_int, "latest_workflow_run", lambda repo, workflow_file="build.yml": {
        "status": "completed", "conclusion": "failure", "html_url": "https://x", "created_at": "y"})
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_build_watch()
    assert any("release build" in p.lower() for p in posts)


def test_only_fires_once_per_day(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.test_runner, "run_test_suite", lambda root: {"passed": 4, "failed": 1, "ok": False})
    monkeypatch.setattr(hb_mod.github_int, "latest_workflow_run", lambda repo, workflow_file="build.yml": None)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._build_watch_done_date = date(2026, 7, 7)
    hb._check_build_watch()
    assert posts == []


def test_disabled_skips(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, build_watch_enabled=False))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_build_watch()
    assert posts == []


def test_no_repo_configured_skips_workflow_check_only(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch, dict(CONF, build_watch_repo=""))
    monkeypatch.setattr(hb_mod.test_runner, "run_test_suite", lambda root: {"passed": 5, "failed": 0, "ok": True})

    def _boom(repo, workflow_file="build.yml"):
        raise AssertionError("must not query workflow status without a configured repo")

    monkeypatch.setattr(hb_mod.github_int, "latest_workflow_run", _boom)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_build_watch()
    assert posts == []
