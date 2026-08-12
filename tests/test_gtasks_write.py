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
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.create_reminder("Reorganize emails", "2026-08-12")
    assert result is None
    service.tasks.return_value.insert.assert_not_called()


def test_create_reminder_case_insensitive_dedup(monkeypatch):
    m = _import_module()
    service = _stub_service([
        {"title": "REORGANIZE EMAILS", "due": "2026-08-12T00:00:00.000Z"},
    ])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.create_reminder("reorganize emails", "2026-08-12")
    assert result is None


def test_create_reminder_inserts_when_no_duplicate(monkeypatch):
    m = _import_module()
    service = _stub_service([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
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
    monkeypatch.setattr(m, "_get_service", lambda: service)
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
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.list_reminders(days=7)
    assert result == [
        {"id": "t1", "title": "Update playlist", "due": "2026-08-12T00:00:00.000Z", "notes": "music"},
    ]


def test_list_reminders_excludes_completed(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.list_reminders(days=7)
    _, kwargs = service.tasks.return_value.list.call_args
    assert kwargs["showCompleted"] is False


def test_list_reminders_passes_due_window(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
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
    monkeypatch.setattr(m, "_get_service", lambda: service)
    result = m.list_reminders(days=7)
    assert [r["id"] for r in result] == ["t1", "t2"]


def test_list_reminders_default_tasklist_is_at_default(monkeypatch):
    m = _import_module()
    service = _stub_service_for_list([])
    monkeypatch.setattr(m, "_get_service", lambda: service)
    m.list_reminders(days=7)
    _, kwargs = service.tasks.return_value.list.call_args
    assert kwargs["tasklist"] == "@default"
