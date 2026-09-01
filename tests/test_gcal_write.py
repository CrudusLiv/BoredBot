"""Section 6: gcal_write — dedup + tag parsing."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


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


def test_create_event_timed_uses_datetime_not_all_day(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.create_event("BIT216", "2026-08-24", start_time="12:00", end_time="14:00")
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"] == {"dateTime": "2026-08-24T12:00:00", "timeZone": "Asia/Kuala_Lumpur"}
    assert body["end"] == {"dateTime": "2026-08-24T14:00:00", "timeZone": "Asia/Kuala_Lumpur"}
    assert "date" not in body["start"]


def test_create_event_timezone_override(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.create_event("X", "2026-08-24", start_time="09:00", end_time="10:00", timezone="UTC")
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"]["timeZone"] == "UTC"


def test_create_event_timed_requires_end_time(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    with pytest.raises(ValueError, match="end_time"):
        m.create_event("X", "2026-08-24", start_time="12:00")


def test_create_event_weekly_recurrence_adds_rrule(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.create_event("BIT216", "2026-08-24", start_time="12:00", end_time="14:00",
                   recur_until="2026-11-27")
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261127T235959Z"]


def test_create_event_location_passes_through(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.create_event("BIT216", "2026-08-24", start_time="12:00", end_time="14:00",
                   location="FLH 2.7")
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["location"] == "FLH 2.7"


def test_create_event_all_day_has_no_recurrence_or_timezone(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.create_event("Plain deadline", "2026-08-24")
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"] == {"date": "2026-08-24"}
    assert "recurrence" not in body
    assert "timeZone" not in body["start"]


def test_create_event_timed_dedup_against_existing_datetime(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"summary": "BIT216", "start": {"dateTime": "2026-08-24T12:00:00+08:00"}},
    ])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.create_event("BIT216", "2026-08-24", start_time="12:00", end_time="14:00")
    assert result is None
    service.events.return_value.insert.assert_not_called()


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


def test_delete_event_no_match_returns_none(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.delete_event("Ghost event", "2026-08-12")
    assert result is None
    service.events.return_value.delete.assert_not_called()


def test_delete_event_one_match_deletes_and_returns_id(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"id": "evt42", "summary": "Reorganize emails", "start": {"date": "2026-08-12"}},
    ])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.delete_event("Reorganize emails", "2026-08-12")
    assert result == "evt42"
    service.events.return_value.delete.assert_called_once_with(
        calendarId="primary", eventId="evt42",
    )


def test_delete_event_case_insensitive_match(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"id": "evt42", "summary": "REORGANIZE EMAILS", "start": {"date": "2026-08-12"}},
    ])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.delete_event("reorganize emails", "2026-08-12")
    assert result == "evt42"


def test_delete_event_multiple_matches_raises_and_does_not_delete(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"id": "evt1", "summary": "Standup", "start": {"date": "2026-08-12"}},
        {"id": "evt2", "summary": "Standup", "start": {"date": "2026-08-12"}},
    ])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    with pytest.raises(ValueError, match="2 events match"):
        m.delete_event("Standup", "2026-08-12")
    service.events.return_value.delete.assert_not_called()
