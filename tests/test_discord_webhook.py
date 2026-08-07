"""Tests for discord_webhook.py — low-level webhook client."""
from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

from integrations import discord_webhook  # noqa: E402


def _mock_response(data: dict | None = None, *, empty: bool = False):
    raw = b"" if empty else json.dumps(data or {}).encode()
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = raw
    return resp


# ────────────────────────────── post ──────────────────────────────────────────

class TestPost:
    def test_wait_true_always_in_url(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.post("https://example.com/hook", content="hi")
        assert "?wait=true" in m.call_args[0][0].full_url

    def test_content_appears_in_body(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.post("https://example.com/hook", content="hello")
        body = json.loads(m.call_args[0][0].data)
        assert body["content"] == "hello"

    def test_embeds_appear_in_body(self):
        embed = {"title": "T", "description": "D"}
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "2"})) as m:
            discord_webhook.post("https://example.com/hook", embeds=[embed])
        body = json.loads(m.call_args[0][0].data)
        assert body["embeds"] == [embed]
        assert "content" not in body

    def test_thread_id_appended_to_query(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "3"})) as m:
            discord_webhook.post("https://example.com/hook", content="x", thread_id="999")
        assert "thread_id=999" in m.call_args[0][0].full_url

    def test_thread_name_in_body(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "4", "channel_id": "555"})) as m:
            discord_webhook.post("https://example.com/hook", content="x", thread_name="New Thread")
        body = json.loads(m.call_args[0][0].data)
        assert body["thread_name"] == "New Thread"

    def test_applied_tags_in_body(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "5"})) as m:
            discord_webhook.post("https://example.com/hook", content="x", applied_tags=["tag1"])
        body = json.loads(m.call_args[0][0].data)
        assert body["applied_tags"] == ["tag1"]

    def test_returns_parsed_json(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "99", "channel_id": "42"})):
            result = discord_webhook.post("https://example.com/hook", content="ok")
        assert result == {"id": "99", "channel_id": "42"}

    def test_user_agent_header_set(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.post("https://example.com/hook", content="x")
        req = m.call_args[0][0]
        assert "DiscordBot" in req.get_header("User-agent")


# ────────────────────────────── edit ──────────────────────────────────────────

class TestEdit:
    def test_patch_method(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.edit("https://example.com/hook", "123", content="updated")
        assert m.call_args[0][0].get_method() == "PATCH"

    def test_message_id_in_url(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.edit("https://example.com/hook", "123", content="updated")
        assert "/messages/123" in m.call_args[0][0].full_url

    def test_thread_id_appended(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.edit("https://example.com/hook", "123", content="x", thread_id="789")
        assert "thread_id=789" in m.call_args[0][0].full_url

    def test_content_in_body(self):
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "1"})) as m:
            discord_webhook.edit("https://example.com/hook", "123", content="new text")
        body = json.loads(m.call_args[0][0].data)
        assert body["content"] == "new text"


# ────────────────────────────── delete ────────────────────────────────────────

class TestDelete:
    def test_delete_method(self):
        with patch("urllib.request.urlopen", return_value=_mock_response(empty=True)) as m:
            discord_webhook.delete("https://example.com/hook", "456")
        assert m.call_args[0][0].get_method() == "DELETE"

    def test_message_id_in_url(self):
        with patch("urllib.request.urlopen", return_value=_mock_response(empty=True)) as m:
            discord_webhook.delete("https://example.com/hook", "456")
        assert "/messages/456" in m.call_args[0][0].full_url

    def test_thread_id_appended(self):
        with patch("urllib.request.urlopen", return_value=_mock_response(empty=True)) as m:
            discord_webhook.delete("https://example.com/hook", "456", thread_id="123")
        assert "thread_id=123" in m.call_args[0][0].full_url

    def test_returns_empty_dict(self):
        with patch("urllib.request.urlopen", return_value=_mock_response(empty=True)):
            result = discord_webhook.delete("https://example.com/hook", "456")
        assert result is None
