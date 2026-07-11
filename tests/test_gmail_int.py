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


# ---- get_body ---------------------------------------------------------------

import base64


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _svc_for_body(payload: dict):
    svc = MagicMock()
    svc.users().messages().get().execute.return_value = {"id": "m1", "payload": payload}
    return svc


def test_get_body_prefers_text_plain():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("plain body")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>html body</p>")}},
        ],
    }
    with patch.object(gi, "_service", return_value=_svc_for_body(payload)):
        assert gi.get_body("m1") == "plain body"


def test_get_body_html_fallback_keeps_links():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)
    html = ('<div>Software Engineer</div>'
            '<div>Acme · KL</div>'
            '<a href="https://example.com/job/1">View job</a>')
    payload = {"mimeType": "text/html", "body": {"data": _b64(html)}}
    with patch.object(gi, "_service", return_value=_svc_for_body(payload)):
        text = gi.get_body("m1")
    assert "Software Engineer" in text
    assert "Acme · KL" in text
    assert "<https://example.com/job/1>" in text
    # block tags became line breaks: title and meta are separate lines
    lines = text.splitlines()
    assert "Software Engineer" in lines


def test_get_body_nested_multipart():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [{
            "mimeType": "multipart/alternative",
            "parts": [{"mimeType": "text/plain", "body": {"data": _b64("nested")}}],
        }],
    }
    with patch.object(gi, "_service", return_value=_svc_for_body(payload)):
        assert gi.get_body("m1") == "nested"


def test_get_body_service_unavailable():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)
    with patch.object(gi, "_service", return_value=None):
        assert gi.get_body("m1") == ""


def test_get_body_api_error_returns_empty():
    import importlib
    import integrations.gmail_int as gi
    importlib.reload(gi)
    svc = MagicMock()
    svc.users().messages().get().execute.side_effect = RuntimeError("boom")
    with patch.object(gi, "_service", return_value=svc):
        assert gi.get_body("m1") == ""
