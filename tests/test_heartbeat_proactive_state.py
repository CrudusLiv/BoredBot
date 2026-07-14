"""State round-trip for the migrated proactive checks' dedup fields."""
from __future__ import annotations

import json

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat


def test_new_state_fields_default_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb._seen_pr_event_ids == []
    assert hb._deadline_fired == {}


def test_new_state_fields_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._seen_pr_event_ids = ["open:owner/repo:1"]
    hb._deadline_fired = {"Passport renewal|2026-08-01": ["72h", "24h"]}
    hb._save_state()

    raw = json.loads((tmp_path / "heartbeat_state.json").read_text(encoding="utf-8"))
    assert raw["seen_pr_event_ids"] == ["open:owner/repo:1"]
    assert raw["deadline_fired"] == {"Passport renewal|2026-08-01": ["72h", "24h"]}

    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb2._seen_pr_event_ids == ["open:owner/repo:1"]
    assert hb2._deadline_fired == {"Passport renewal|2026-08-01": ["72h", "24h"]}


def test_git_todo_done_date_defaults_none_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb._git_todo_done_date is None
    from datetime import date
    hb._git_todo_done_date = date(2026, 7, 7)
    hb._save_state()
    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb2._git_todo_done_date == date(2026, 7, 7)


def test_build_watch_fields_default_and_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb._build_watch_done_date is None
    assert hb._last_test_ok is None
    assert hb._last_workflow_conclusion is None

    from datetime import date
    hb._build_watch_done_date = date(2026, 7, 7)
    hb._last_test_ok = False
    hb._last_workflow_conclusion = "failure"
    hb._save_state()

    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb2._build_watch_done_date == date(2026, 7, 7)
    assert hb2._last_test_ok is False
    assert hb2._last_workflow_conclusion == "failure"
