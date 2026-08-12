"""voice/ui_server.py::reminders_list -- GET /cmd/reminders. Mirrors
calendar_events(): a thread-executor call into integrations.gtasks_write,
mocked here so no real Google Tasks API call happens."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from voice import ui_server


def _import_gtasks_write():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from integrations import gtasks_write  # type: ignore
    return gtasks_write


def test_reminders_returns_list_reminders_result(monkeypatch):
    m = _import_gtasks_write()
    monkeypatch.setattr(m, "list_reminders", lambda days=7: [
        {"id": "t1", "title": "Update playlist", "due": "2026-08-12T00:00:00.000Z", "notes": ""},
    ])
    client = TestClient(ui_server.app)
    r = client.get("/cmd/reminders")
    assert r.status_code == 200
    assert r.json()["reminders"] == [
        {"id": "t1", "title": "Update playlist", "due": "2026-08-12T00:00:00.000Z", "notes": ""},
    ]


def test_reminders_error_is_reported_not_unhandled(monkeypatch):
    m = _import_gtasks_write()

    def _boom(days=7):
        raise RuntimeError("tasks api down")

    monkeypatch.setattr(m, "list_reminders", _boom)
    client = TestClient(ui_server.app)
    r = client.get("/cmd/reminders")
    assert r.status_code == 200
    d = r.json()
    assert "error" in d
    assert d["reminders"] == []


def test_reminders_passes_seven_day_window(monkeypatch):
    m = _import_gtasks_write()
    captured = {}

    def fake_list(days=7):
        captured["days"] = days
        return []

    monkeypatch.setattr(m, "list_reminders", fake_list)
    client = TestClient(ui_server.app)
    client.get("/cmd/reminders")
    assert captured["days"] == 7
