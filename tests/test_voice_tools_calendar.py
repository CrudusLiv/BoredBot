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


def test_deletes_event_and_reports_title_and_date(monkeypatch):
    m = _gcal_write_module()
    calls = []
    monkeypatch.setattr(
        m, "delete_event",
        lambda title, date: calls.append((title, date)) or "evt42",
    )
    result = calendar_tools.delete_calendar_event("Reorganize emails", "2026-08-12")
    assert calls == [("Reorganize emails", "2026-08-12")]
    assert "Reorganize emails" in result
    assert "2026-08-12" in result


def test_delete_no_match_is_reported(monkeypatch):
    m = _gcal_write_module()
    monkeypatch.setattr(m, "delete_event", lambda title, date: None)
    result = calendar_tools.delete_calendar_event("Ghost", "2026-08-12")
    assert "no event" in result.lower()


def test_delete_ambiguous_match_is_reported(monkeypatch):
    m = _gcal_write_module()

    def _boom(title, date):
        raise ValueError("2 events match 'Standup' on 2026-08-12: 'Standup', 'Standup'")

    monkeypatch.setattr(m, "delete_event", _boom)
    result = calendar_tools.delete_calendar_event("Standup", "2026-08-12")
    assert "can't delete" in result.lower()
    assert "2 events match" in result


def test_delete_gcal_error_is_reported_not_raised(monkeypatch):
    m = _gcal_write_module()

    def _boom(title, date):
        raise RuntimeError("no creds")

    monkeypatch.setattr(m, "delete_event", _boom)
    result = calendar_tools.delete_calendar_event("Dentist", "2026-08-10")
    assert "unavailable" in result.lower()


def _gtasks_write_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
    from integrations import gtasks_write  # type: ignore
    return gtasks_write


def test_creates_reminder_and_reports_title_and_date(monkeypatch):
    m = _gtasks_write_module()
    calls = []
    monkeypatch.setattr(
        m, "create_reminder",
        lambda title, date, description="": calls.append((title, date, description)) or "task123",
    )
    result = calendar_tools.create_reminder("Reorganize emails", "2026-08-12")
    assert calls == [("Reorganize emails", "2026-08-12", "")]
    assert "Reorganize emails" in result
    assert "2026-08-12" in result


def test_duplicate_reminder_is_reported_not_silently_ignored(monkeypatch):
    m = _gtasks_write_module()
    monkeypatch.setattr(m, "create_reminder", lambda title, date, description="": None)
    result = calendar_tools.create_reminder("Reorganize emails", "2026-08-12")
    assert "already exists" in result.lower()


def test_reminder_error_is_reported_not_raised(monkeypatch):
    m = _gtasks_write_module()

    def _boom(title, date, description=""):
        raise RuntimeError("no creds")

    monkeypatch.setattr(m, "create_reminder", _boom)
    result = calendar_tools.create_reminder("Reorganize emails", "2026-08-12")
    assert "unavailable" in result.lower()


def test_lists_upcoming_reminders(monkeypatch):
    m = _gtasks_write_module()
    monkeypatch.setattr(
        m, "list_reminders",
        lambda days=7: [
            {"id": "t1", "title": "Update playlist", "due": "2026-08-12T00:00:00.000Z", "notes": ""},
        ],
    )
    result = calendar_tools.upcoming_reminders(days=7)
    assert "Update playlist" in result
    assert "2026-08-12" in result


def test_no_upcoming_reminders_is_reported(monkeypatch):
    m = _gtasks_write_module()
    monkeypatch.setattr(m, "list_reminders", lambda days=7: [])
    result = calendar_tools.upcoming_reminders(days=7)
    assert "no reminders" in result.lower()


def test_list_reminders_error_is_reported_not_raised(monkeypatch):
    m = _gtasks_write_module()

    def _boom(days=7):
        raise RuntimeError("no creds")

    monkeypatch.setattr(m, "list_reminders", _boom)
    result = calendar_tools.upcoming_reminders(days=7)
    assert "unavailable" in result.lower()


def test_completes_reminder_and_reports_title(monkeypatch):
    m = _gtasks_write_module()
    calls = []
    monkeypatch.setattr(
        m, "complete_reminder",
        lambda title: calls.append(title) or "task123",
    )
    result = calendar_tools.complete_reminder("Reorganize emails")
    assert calls == ["Reorganize emails"]
    assert "Reorganize emails" in result
    assert "done" in result.lower()


def test_complete_reminder_no_match_is_reported(monkeypatch):
    m = _gtasks_write_module()
    monkeypatch.setattr(m, "complete_reminder", lambda title: None)
    result = calendar_tools.complete_reminder("Ghost")
    assert "no reminder" in result.lower()


def test_complete_reminder_ambiguous_match_is_reported(monkeypatch):
    m = _gtasks_write_module()

    def _boom(title):
        raise ValueError("2 reminders match 'Standup' -- be more specific.")

    monkeypatch.setattr(m, "complete_reminder", _boom)
    result = calendar_tools.complete_reminder("Standup")
    assert "can't mark it done" in result.lower()
    assert "2 reminders match" in result


def test_complete_reminder_error_is_reported_not_raised(monkeypatch):
    m = _gtasks_write_module()

    def _boom(title):
        raise RuntimeError("no creds")

    monkeypatch.setattr(m, "complete_reminder", _boom)
    result = calendar_tools.complete_reminder("Reorganize emails")
    assert "unavailable" in result.lower()
