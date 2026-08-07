"""voice/tools/calendar.py::create_calendar_event — thin wrapper around
gcal_write.create_event with duplicate/error messaging for voice replies."""
from __future__ import annotations

import sys
from pathlib import Path

from voice.tools import calendar as calendar_tools


def _gcal_write_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
    from integrations import gcal_write  # type: ignore
    return gcal_write


def test_creates_event_and_reports_title_and_date(monkeypatch):
    m = _gcal_write_module()
    calls = []
    monkeypatch.setattr(
        m, "create_event",
        lambda title, date, description="": calls.append((title, date, description)) or "evt123",
    )
    result = calendar_tools.create_calendar_event("Dentist", "2026-08-10")
    assert calls == [("Dentist", "2026-08-10", "")]
    assert "Dentist" in result
    assert "2026-08-10" in result


def test_duplicate_event_is_reported_not_silently_ignored(monkeypatch):
    m = _gcal_write_module()
    monkeypatch.setattr(m, "create_event", lambda title, date, description="": None)
    result = calendar_tools.create_calendar_event("Dentist", "2026-08-10")
    assert "already exists" in result.lower() or "duplicate" in result.lower()


def test_gcal_error_is_reported_not_raised(monkeypatch):
    m = _gcal_write_module()

    def _boom(title, date, description=""):
        raise RuntimeError("no creds")

    monkeypatch.setattr(m, "create_event", _boom)
    result = calendar_tools.create_calendar_event("Dentist", "2026-08-10")
    assert "unavailable" in result.lower()


def test_description_is_forwarded(monkeypatch):
    m = _gcal_write_module()
    calls = []
    monkeypatch.setattr(
        m, "create_event",
        lambda title, date, description="": calls.append(description) or "evt123",
    )
    calendar_tools.create_calendar_event("Dentist", "2026-08-10", description="annual checkup")
    assert calls == ["annual checkup"]
