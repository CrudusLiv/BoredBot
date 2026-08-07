"""voice/tools/__init__.py — create_calendar_event must be registered so
its description reaches the system prompt (voice.tools._tool_descriptions()),
even though voice/mcp_server.py is what actually executes it."""
from __future__ import annotations

from voice import tools


def test_create_calendar_event_is_registered():
    names = {t["name"] for t in tools.REGISTRY}
    assert "create_calendar_event" in names
