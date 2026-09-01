"""voice/ui_server.py::calendar_events -- GET /cmd/calendar. A thread-
executor call into integrations.gcal_int.upcoming, mocked here so no real
Google Calendar API call happens. Covers the date-range query params the
month/week grid uses."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from voice import ui_server


def _import_gcal_int():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from integrations import gcal_int  # type: ignore
    return gcal_int


def test_calendar_defaults_to_a_week(monkeypatch):
    m = _import_gcal_int()
    calls = []
    monkeypatch.setattr(m, "upcoming", lambda **kw: calls.append(kw) or [])
    client = TestClient(ui_server.app)
    r = client.get("/cmd/calendar")
    assert r.status_code == 200
    assert calls == [{"days": 7, "days_back": 0, "max_results": 500}]


def test_calendar_forwards_range_params(monkeypatch):
    m = _import_gcal_int()
    calls = []
    monkeypatch.setattr(m, "upcoming", lambda **kw: calls.append(kw) or [])
    client = TestClient(ui_server.app)
    r = client.get("/cmd/calendar", params={"days_back": 10, "days": 42})
    assert r.status_code == 200
    assert calls == [{"days": 42, "days_back": 10, "max_results": 500}]


def test_calendar_returns_events_under_events_key(monkeypatch):
    m = _import_gcal_int()
    events = [{"id": "e1", "summary": "BIT216", "start": "2026-08-31T12:00:00+08:00",
              "end": "2026-08-31T14:00:00+08:00", "location": "FLH 2.7", "description": ""}]
    monkeypatch.setattr(m, "upcoming", lambda **kw: events)
    client = TestClient(ui_server.app)
    r = client.get("/cmd/calendar")
    assert r.status_code == 200
    assert r.json() == {"events": events}
