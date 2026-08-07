"""Section 6: gcal_write — dedup + tag parsing."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_module():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from integrations import gcal_write  # type: ignore
    return gcal_write


def _stub_service(existing_events: list[dict]) -> MagicMock:
    """Build a mock Google Calendar API service.events() chain."""
    service = MagicMock()
    events_resource = service.events.return_value
    events_resource.list.return_value.execute.return_value = {"items": existing_events}
    insert_call = events_resource.insert.return_value
    insert_call.execute.return_value = {"id": "new_evt"}
    return service


def test_create_event_returns_none_on_duplicate(monkeypatch):
    m = _import_module()
    service = _stub_service([{"summary": "DIP209 deadline", "start": {"date": "2026-06-01"}}])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.create_event("DIP209 deadline", "2026-06-01")
    assert result is None
    service.events.return_value.insert.assert_not_called()


def test_create_event_case_insensitive_dedup(monkeypatch):
    m = _import_module()
    service = _stub_service([{"summary": "dip209 DEADLINE", "start": {"date": "2026-06-01"}}])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.create_event("DIP209 deadline", "2026-06-01")
    assert result is None


def test_create_event_inserts_when_no_duplicate(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.create_event("New deadline", "2026-06-02", description="hello")
    assert result == "new_evt"
    service.events.return_value.insert.assert_called_once()
    args, kwargs = service.events.return_value.insert.call_args
    body = kwargs["body"]
    assert body["summary"] == "New deadline"
    assert body["start"]["date"] == "2026-06-02"
    assert body["end"]["date"] == "2026-06-03"  # all-day events end is exclusive
    assert body["description"] == "hello"


def test_parse_gcal_tag_simple():
    m = _import_module()
    matches = m.parse_gcal_tags("gcal: 2026-06-10 | DIP209 capstone deadline")
    assert matches == [("2026-06-10", "DIP209 capstone deadline")]


def test_parse_gcal_tag_skips_synced():
    m = _import_module()
    matches = m.parse_gcal_tags("gcal: 2026-06-10 | already done [synced:abc123]")
    assert matches == []


def test_parse_deadline_row():
    m = _import_module()
    parsed = m.parse_deadlines_md("- 2026-06-10 — DIP209 — Capstone deadline\n- nogcal: 2026-06-11 — CS101 — skip me\n")
    assert parsed == [("2026-06-10", "DIP209 — Capstone deadline")]
