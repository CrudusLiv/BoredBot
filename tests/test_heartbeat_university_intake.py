"""voice/heartbeat.py::_check_university_intake — walk D:\\University into the vault."""
from __future__ import annotations

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice import university_intake as ui
from voice.heartbeat import Heartbeat

BASE_CONF = {
    "university_intake_enabled": True,
    "university_intake_root": "D:/University",
    "university_intake_mode": "per-file",
    "university_intake_extensions": [".txt"],
    "university_intake_denylist": [],
    "university_intake_max_chars": 20000,
    "university_intake_deadline_detection": True,
}


def _hb(tmp_path, monkeypatch, conf):
    root_dir = tmp_path / "University"
    root_dir.mkdir()
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: {**conf, "university_intake_root": str(root_dir)})
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: tmp_path / "vault")
    (tmp_path / "vault").mkdir()
    posts: list[str] = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO", meta=None: posts.append(text))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None, power_fn=lambda: None)
    return hb, posts


def test_disabled_does_not_call_run_intake(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: called.append(1))
    hb, posts = _hb(tmp_path, monkeypatch, dict(BASE_CONF, university_intake_enabled=False))
    hb._check_university_intake()
    assert called == [] and posts == []


def test_added_notes_post_one_summary(tmp_path, monkeypatch):
    res = ui.IntakeResult(added=["coursework/bit216/a.md", "coursework/bit216/b.md",
                                 "coursework/fec100/c.md"])
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: res)
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    assert len(posts) == 1
    assert "Coursework" in posts[0] and len(posts[0]) <= 160


def test_no_changes_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: ui.IntakeResult())
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    assert posts == []


def test_deadlines_forwarded_to_add_rows(tmp_path, monkeypatch):
    res = ui.IntakeResult(added=["coursework/bit216/a.md"],
                          deadlines=[("2026-10-15", "BIT216 — a")])
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: res)
    seen = []
    monkeypatch.setattr("voice.deadlines.add_rows", lambda pairs: seen.append(pairs) or [])
    hb, _ = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    assert seen == [[("2026-10-15", "BIT216 — a")]]


def test_partial_result_says_more_next_tick(tmp_path, monkeypatch):
    res = ui.IntakeResult(added=[f"coursework/bit216/a{i}.md" for i in range(200)],
                          partial=True)
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: res)
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    assert len(posts) == 1
    assert "more next tick" in posts[0] and len(posts[0]) <= 160


def test_notice_reports_deadline_count(tmp_path, monkeypatch):
    res = ui.IntakeResult(added=["coursework/bit216/a.md"],
                          deadlines=[("2026-10-15", "BIT216 — a"),
                                     ("2026-11-01", "BIT216 — b")])
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: res)
    monkeypatch.setattr("voice.deadlines.add_rows", lambda pairs: ["r1", "r2"])
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    assert len(posts) == 1
    assert "+2 deadlines" in posts[0] and len(posts[0]) <= 160


def test_wide_backfill_keeps_markers_when_truncating(tmp_path, monkeypatch):
    res = ui.IntakeResult(
        added=[f"coursework/c{i:02d}/n.md" for i in range(60)], partial=True)
    monkeypatch.setattr(ui, "run_intake", lambda *a, **k: res)
    monkeypatch.setattr("voice.deadlines.add_rows",
                        lambda pairs: ["r1", "r2", "r3", "r4", "r5"])
    res.deadlines = [("2026-10-15", "x")]
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    assert len(posts) == 1
    assert len(posts[0]) <= 160
    assert "+5 deadlines" in posts[0]
    assert "more next tick" in posts[0]


def test_manifest_saved_even_when_run_intake_raises(tmp_path, monkeypatch):
    def boom(root, vault, *, manifest, config):
        manifest["files"]["University/x/Sem 1/BIT216/a.txt"] = {
            "hash": "h", "mtime": 1.0, "size": 3, "note": "coursework/bit216/a.md"}
        raise RuntimeError("mid-walk crash")
    monkeypatch.setattr(ui, "run_intake", boom)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()          # must not raise
    saved = (tmp_path / "university_intake.json").read_text(encoding="utf-8")
    assert "BIT216/a.txt" in saved
    assert posts == []


def test_run_intake_exception_does_not_raise(tmp_path, monkeypatch):
    def boom(*a, **k): raise RuntimeError("bang")
    monkeypatch.setattr(ui, "run_intake", boom)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(a))
    hb, posts = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()          # must not raise
    assert posts == []
    assert any("university_intake" in " ".join(str(x) for x in a) for a in printed)


def test_manifest_persists_between_runs(tmp_path, monkeypatch):
    def fake_run(root, vault, *, manifest, config):
        manifest["files"]["University/x/Sem 1/BIT216/a.txt"] = {
            "hash": "h", "mtime": 1.0, "note": "coursework/bit216/a.md"}
        return ui.IntakeResult(added=["coursework/bit216/a.md"])
    monkeypatch.setattr(ui, "run_intake", fake_run)
    hb, _ = _hb(tmp_path, monkeypatch, BASE_CONF)
    hb._check_university_intake()
    saved = (tmp_path / "university_intake.json").read_text(encoding="utf-8")
    assert "BIT216/a.txt" in saved


def test_schedule_and_enabled_registration():
    names = {row[0] for row in Heartbeat._SCHEDULE}
    assert "university_intake" in names
    assert Heartbeat._ENABLED_KEYS["university_intake"] == "university_intake_enabled"
