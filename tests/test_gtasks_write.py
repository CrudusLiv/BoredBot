"""Google Tasks reminders -- dedup + create. Mirrors test_gcal_write.py's
mock-service pattern for the Tasks v1 API shape."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_module():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from integrations import gtasks_write  # type: ignore
    return gtasks_write


def _stub_service(existing_tasks: list[dict]) -> MagicMock:
    service = MagicMock()
    tasks_resource = service.tasks.return_value
    tasks_resource.list.return_value.execute.return_value = {"items": existing_tasks}
    insert_call = tasks_resource.insert.return_value
    insert_call.execute.return_value = {"id": "new_task"}
    return service


def test_create_reminder_returns_none_on_duplicate(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"title": "Reorganize emails", "due": "2026-08-12T00:00:00.000Z"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.create_reminder("Reorganize emails", "2026-08-12")
    assert result is None
    service.tasks.return_value.insert.assert_not_called()


def test_create_reminder_case_insensitive_dedup(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"title": "REORGANIZE EMAILS", "due": "2026-08-12T00:00:00.000Z"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.create_reminder("reorganize emails", "2026-08-12")
    assert result is None


def test_create_reminder_inserts_when_no_duplicate(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.create_reminder("New reminder", "2026-08-13", description="hello")
    assert result == "new_task"
    service.tasks.return_value.insert.assert_called_once()
    args, kwargs = service.tasks.return_value.insert.call_args
    body = kwargs["body"]
    assert body["title"] == "New reminder"
    assert body["due"] == "2026-08-13T00:00:00.000Z"
    assert body["notes"] == "hello"


def test_create_reminder_default_tasklist_is_at_default(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    m.create_reminder("New reminder", "2026-08-13")
    _, kwargs = service.tasks.return_value.insert.call_args
    assert kwargs["tasklist"] == "@default"


def _stub_service_for_list(items: list[dict]) -> MagicMock:
    service = MagicMock()
    service.tasks.return_value.list.return_value.execute.return_value = {"items": items}
    return service


def test_list_reminders_maps_fields(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([
        {"id": "t1", "title": "Update playlist", "due": "2026-08-12T00:00:00.000Z", "notes": "music"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.list_reminders(days=7)
    assert result == [
        {"id": "t1", "title": "Update playlist", "due": "2026-08-12T00:00:00.000Z", "notes": "music"},
    ]


def test_list_reminders_excludes_completed(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    m.list_reminders(days=7)
    _, kwargs = service.tasks.return_value.list.call_args
    assert kwargs["showCompleted"] is False


def test_list_reminders_passes_due_window(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    m.list_reminders(days=7)
    _, kwargs = service.tasks.return_value.list.call_args
    assert "dueMin" in kwargs
    assert "dueMax" in kwargs
    assert kwargs["dueMin"] < kwargs["dueMax"]


def test_list_reminders_sorted_by_due_date(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([
        {"id": "t2", "title": "Later", "due": "2026-08-14T00:00:00.000Z", "notes": ""},
        {"id": "t1", "title": "Sooner", "due": "2026-08-12T00:00:00.000Z", "notes": ""},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.list_reminders(days=7)
    assert [r["id"] for r in result] == ["t1", "t2"]


def test_list_reminders_default_tasklist_is_at_default(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    m.list_reminders(days=7)
    _, kwargs = service.tasks.return_value.list.call_args
    assert kwargs["tasklist"] == "@default"


def test_due_reminders_maps_fields(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([
        {"id": "t1", "title": "Overdue thing", "due": "2026-08-10T00:00:00.000Z", "notes": "n"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.due_reminders()
    assert result == [
        {"id": "t1", "title": "Overdue thing", "due": "2026-08-10T00:00:00.000Z", "notes": "n"},
    ]


def test_due_reminders_has_no_lower_bound(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    m.due_reminders()
    _, kwargs = service.tasks.return_value.list.call_args
    assert "dueMin" not in kwargs
    assert "dueMax" in kwargs
    assert kwargs["showCompleted"] is False


def test_due_reminders_dueMax_reaches_past_today(monkeypatch):
    """The Tasks API's dueMax filter compares by whole calendar day: a
    reminder due exactly today (always stored as T00:00:00.000Z) is only
    included once dueMax's date is tomorrow or later. dueMax must never be
    left at the exact instant of the call, or a same-day due reminder is
    silently dropped for the entire day it's due -- see due_reminders()'s
    docstring."""
    from datetime import datetime, timezone

    m = _import_module()
    service = _stub_service_for_list([])
    fixed_now = datetime(2026, 8, 15, 8, 47, 0, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    monkeypatch.setattr(m, "datetime", _FixedDatetime)
    m.due_reminders()
    _, kwargs = service.tasks.return_value.list.call_args
    assert kwargs["dueMax"] >= "2026-08-16T00:00:00"


def test_complete_reminder_marks_matching_task_done(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([
        {"id": "t1", "title": "Renew passport"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    result = m.complete_reminder("renew passport")
    assert result == "t1"
    _, kwargs = service.tasks.return_value.patch.call_args
    assert kwargs["tasklist"] == "@default"
    assert kwargs["task"] == "t1"
    assert kwargs["body"] == {"status": "completed"}


def test_complete_reminder_no_match_returns_none(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    assert m.complete_reminder("Ghost") is None
    service.tasks.return_value.patch.assert_not_called()


def test_complete_reminder_ambiguous_raises(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([
        {"id": "t1", "title": "Standup"},
        {"id": "t2", "title": "Standup"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda **_k: service)
    import pytest
    with pytest.raises(ValueError):
        m.complete_reminder("Standup")
    service.tasks.return_value.patch.assert_not_called()
