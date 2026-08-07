"""Smoke tests for gmail_int — Google API is mocked, no network calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))

import integrations._env  # noqa: F401


def _make_api_mock(messages: list[dict] | None = None):
    """Return a mock gmail service that returns `messages` from list_recent."""
    if messages is None:
        messages = [
            {
                "id": "msg1",
                "snippet": "Hello there",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Test Subject"},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Date", "value": "Sat, 14 Jun 2026 10:00:00 +0800"},
                    ]
                },
            }
        ]

    svc = MagicMock()
    svc.users().messages().list().execute.return_value = {
        "messages": [{"id": m["id"]} for m in messages]
    }
    svc.users().messages().get().execute.side_effect = [m for m in messages]
    return svc


def test_service_returns_none_without_google_client(monkeypatch):
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)
    monkeypatch.setattr(gi, "get_credentials", lambda: MagicMock())
    with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
        result = gi._service()
    assert result is None


def test_list_recent_returns_parsed_list():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)

    mock_svc = _make_api_mock()
    with patch.object(gi, "_service", return_value=mock_svc):
        items = gi.list_recent(days=7, max_results=5)

    assert len(items) == 1
    assert items[0]["subject"] == "Test Subject"
    assert items[0]["from"] == "sender@example.com"
    assert items[0]["snippet"] == "Hello there"
    assert items[0]["id"] == "msg1"


def test_list_recent_empty_when_service_unavailable():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)

    with patch.object(gi, "_service", return_value=None):
        items = gi.list_recent()

    assert items == []


def test_list_recent_empty_inbox():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)

    mock_svc = MagicMock()
    mock_svc.users().messages().list().execute.return_value = {}
    with patch.object(gi, "_service", return_value=mock_svc):
        items = gi.list_recent()

    assert items == []


def test_handle_query_recent_json(capsys):
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)

    mock_svc = _make_api_mock()
    with patch.object(gi, "_service", return_value=mock_svc):
        rc = gi.handle_query(["recent", "--days", "3", "--max", "5", "--json"])

    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert data[0]["subject"] == "Test Subject"


def test_handle_query_recent_human(capsys):
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)

    mock_svc = _make_api_mock()
    with patch.object(gi, "_service", return_value=mock_svc):
        rc = gi.handle_query(["recent"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Test Subject" in captured.out
    assert "sender@example.com" in captured.out
