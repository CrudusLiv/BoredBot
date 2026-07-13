"""Smoke tests for outlook_int -- Microsoft Graph HTTP calls are mocked, no network."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))

import integrations._env  # noqa: F401


def _iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_messages_response(messages: list[dict]):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"value": messages}
    return resp


def test_list_recent_returns_empty_without_token():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value=None):
        assert oi.list_recent() == []


def test_list_recent_parses_and_trims_to_days_window():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)

    messages = [
        {
            "id": "m1",
            "subject": "Assignment due",
            "from": {"emailAddress": {"address": "prof@helplive.edu.my", "name": "Prof X"}},
            "receivedDateTime": _iso(2),
            "bodyPreview": "Please submit by Friday",
        },
        {
            "id": "m2",
            "subject": "Old newsletter",
            "from": {"emailAddress": {"address": "news@example.com", "name": "News"}},
            "receivedDateTime": _iso(30),
            "bodyPreview": "Old stuff",
        },
    ]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        items = oi.list_recent(days=7, max_results=30)

    assert len(items) == 1
    assert items[0]["id"] == "m1"
    assert items[0]["subject"] == "Assignment due"
    assert items[0]["from"] == "Prof X <prof@helplive.edu.my>"
    assert items[0]["snippet"] == "Please submit by Friday"


def test_list_recent_empty_inbox():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = _make_messages_response([])
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        assert oi.list_recent() == []


def test_list_recent_returns_empty_on_request_error():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", side_effect=oi.requests.RequestException("boom")):
        assert oi.list_recent() == []


def test_list_recent_returns_empty_on_json_parse_error():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = ValueError("bad json")
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        assert oi.list_recent() == []


def test_list_recent_includes_message_with_fractional_seconds():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)

    messages = [
        {
            "id": "m1",
            "subject": "Assignment due",
            "from": {"emailAddress": {"address": "prof@helplive.edu.my", "name": "Prof X"}},
            "receivedDateTime": "2026-07-11T08:23:45.1234567Z",
            "bodyPreview": "Please submit by Friday",
        },
    ]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        items = oi.list_recent(days=7, max_results=30)

    assert len(items) == 1
    assert items[0]["id"] == "m1"
    assert items[0]["subject"] == "Assignment due"
    assert items[0]["date"] == "2026-07-11T08:23:45.1234567Z"


def test_get_body_returns_empty_without_token():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value=None):
        assert oi.get_body("m1") == ""


def test_get_body_converts_html_content():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "body": {"contentType": "html", "content": "<div>Hello</div><div>World</div>"}
    }
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        text = oi.get_body("m1")
    assert "Hello" in text
    assert "World" in text


def test_get_body_passes_through_text_content():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"body": {"contentType": "text", "content": "plain body"}}
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        assert oi.get_body("m1") == "plain body"


def test_get_body_returns_empty_on_request_error():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", side_effect=oi.requests.RequestException("boom")):
        assert oi.get_body("m1") == ""


def test_get_body_returns_empty_on_json_parse_error():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = ValueError("bad json")
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        assert oi.get_body("m1") == ""


def test_handle_query_recent_json(capsys):
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    messages = [{
        "id": "m1",
        "subject": "Test Subject",
        "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
        "receivedDateTime": _iso(1),
        "bodyPreview": "Hello there",
    }]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        rc = oi.handle_query(["recent", "--days", "3", "--max", "5", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["subject"] == "Test Subject"


def test_handle_query_recent_human(capsys):
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    messages = [{
        "id": "m1",
        "subject": "Test Subject",
        "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
        "receivedDateTime": _iso(1),
        "bodyPreview": "Hello there",
    }]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        rc = oi.handle_query(["recent"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Test Subject" in out
    assert "sender@example.com" in out
