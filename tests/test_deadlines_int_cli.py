"""query.py deadlines scan / deadlines import -- new integration module."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import deadlines_int  # noqa: E402
from core import imminent  # noqa: E402
from voice import deadlines as voice_deadlines  # noqa: E402


def test_scan_prints_actionable_items(monkeypatch, capsys):
    buckets = {"urgent": [{"key": "k1", "due": "2026-08-06", "course": "CS", "title": "HW", "days": 1, "bucket": "urgent"}]}
    monkeypatch.setattr(imminent, "scan", lambda: buckets)
    monkeypatch.setattr(imminent, "actionable", lambda b: b["urgent"])

    rc = deadlines_int.handle_query(["scan", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"items": buckets["urgent"]}


def test_import_fetches_events_and_prints_added(monkeypatch, capsys):
    events = [{"summary": "Rent due", "start": "2026-08-10"}]
    monkeypatch.setattr(deadlines_int.gcal_int, "upcoming", lambda days, max_results: events)
    monkeypatch.setattr(voice_deadlines, "import_from_events", lambda evs, kw: ["2026-08-10 - Rent due"])
    monkeypatch.setattr(deadlines_int.voice_config, "load", lambda: {"deadline_import_keywords": ["due"]})

    rc = deadlines_int.handle_query(["import", "--days", "10", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"added": ["2026-08-10 - Rent due"]}


def test_import_defaults_to_30_day_lookahead(monkeypatch):
    captured = {}
    monkeypatch.setattr(deadlines_int.gcal_int, "upcoming", lambda days, max_results: captured.update(days=days) or [])
    monkeypatch.setattr(voice_deadlines, "import_from_events", lambda evs, kw: [])
    monkeypatch.setattr(deadlines_int.voice_config, "load", lambda: {})

    deadlines_int.handle_query(["import", "--json"])

    assert captured["days"] == 30
