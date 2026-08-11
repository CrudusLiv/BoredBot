"""voice/tools/__init__.py — create_calendar_event must be registered in
this legacy REGISTRY/dispatch() list, even though voice/agent_tools.py is
what actually executes it for live conversation."""
from __future__ import annotations

from voice import tools


def test_create_calendar_event_is_registered():
    names = {t["name"] for t in tools.REGISTRY}
    assert "create_calendar_event" in names
