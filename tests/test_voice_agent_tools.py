"""Tests for voice.agent_tools's sync tool functions: each must still reach
the exact same underlying function, and confirmation-gated tools must still
block on voice.safety.confirm_with_reason before running. Supersedes
tests/test_voice_mcp_server.py, which covered the retired subprocess
mcp_server.py version of the same wrappers."""
from __future__ import annotations

import pytest

from voice import agent_tools


def test_search_vault_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agent_tools, "search_vault",
        lambda query, top_k=5: seen.update(query=query, top_k=top_k) or "OK",
    )
    result = agent_tools.search_vault_tool(query="deadlines", top_k=3)
    assert result == "OK"
    assert seen == {"query": "deadlines", "top_k": 3}


def test_upcoming_events_delegates(monkeypatch):
    monkeypatch.setattr(agent_tools, "upcoming_events", lambda days=7: f"{days} days")
    assert agent_tools.upcoming_events_tool(days=14) == "14 days"


def test_upcoming_reminders_delegates(monkeypatch):
    monkeypatch.setattr(agent_tools, "upcoming_reminders", lambda days=7: f"{days} days")
    assert agent_tools.upcoming_reminders_tool(days=14) == "14 days"


@pytest.mark.parametrize("tool_fn_name,wrapper_name,arg_name,arg_value", [
    ("append_note", "append_note_tool", "path", "x.md"),
    ("create_note", "create_note_tool", "path", "y.md"),
    ("forget", "forget_fact_tool", "key", "some-key"),
    ("complete_deadline", "complete_deadline_tool", "query", "renew passport"),
    ("create_calendar_event", "create_calendar_event_tool", "title", "Dentist"),
    ("delete_calendar_event", "delete_calendar_event_tool", "title", "Dentist"),
    ("create_reminder", "create_reminder_tool", "title", "Reorganize emails"),
])
def test_confirmation_gated_tools_block_on_confirm(
    monkeypatch, tool_fn_name, wrapper_name, arg_name, arg_value,
):
    monkeypatch.setattr(agent_tools, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        agent_tools, "confirm_with_reason",
        lambda name, args: (False, "cancelled"),
    )
    underlying_called = []
    monkeypatch.setattr(
        agent_tools, tool_fn_name, lambda **kw: underlying_called.append(kw),
    )
    wrapper = getattr(agent_tools, wrapper_name)
    kwargs = {arg_name: arg_value}
    if wrapper_name in ("append_note_tool", "create_note_tool"):
        kwargs["text"] = "body"
    if wrapper_name in ("create_calendar_event_tool", "delete_calendar_event_tool", "create_reminder_tool"):
        kwargs["date"] = "2026-08-10"
    result = wrapper(**kwargs)
    assert underlying_called == []
    assert result == "[cancelled by user]"


def test_confirmation_approved_runs_underlying_tool(monkeypatch):
    monkeypatch.setattr(agent_tools, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        agent_tools, "confirm_with_reason", lambda name, args: (True, "user"),
    )
    monkeypatch.setattr(
        agent_tools, "create_note", lambda path, text: f"created {path}",
    )
    result = agent_tools.create_note_tool(path="z.md", text="hi")
    assert result == "created z.md"


def test_non_gated_tool_never_calls_confirm(monkeypatch):
    called = []
    monkeypatch.setattr(
        agent_tools, "confirm_with_reason", lambda *a: called.append(1),
    )
    monkeypatch.setattr(agent_tools, "requires_confirmation", lambda name: False)
    monkeypatch.setattr(agent_tools, "search_vault", lambda query, top_k=5: "OK")
    agent_tools.search_vault_tool(query="x")
    assert called == []


def test_create_calendar_event_approved_runs_underlying_tool(monkeypatch):
    monkeypatch.setattr(agent_tools, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        agent_tools, "confirm_with_reason", lambda name, args: (True, "user"),
    )
    monkeypatch.setattr(
        agent_tools, "create_calendar_event",
        lambda title, date, description="": f"created {title} on {date}",
    )
    result = agent_tools.create_calendar_event_tool(title="Dentist", date="2026-08-10")
    assert result == "created Dentist on 2026-08-10"


def test_delete_calendar_event_approved_runs_underlying_tool(monkeypatch):
    monkeypatch.setattr(agent_tools, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        agent_tools, "confirm_with_reason", lambda name, args: (True, "user"),
    )
    monkeypatch.setattr(
        agent_tools, "delete_calendar_event",
        lambda title, date: f"deleted {title} on {date}",
    )
    result = agent_tools.delete_calendar_event_tool(title="Dentist", date="2026-08-10")
    assert result == "deleted Dentist on 2026-08-10"


def test_create_reminder_approved_runs_underlying_tool(monkeypatch):
    monkeypatch.setattr(agent_tools, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        agent_tools, "confirm_with_reason", lambda name, args: (True, "user"),
    )
    monkeypatch.setattr(
        agent_tools, "create_reminder",
        lambda title, date, description="": f"created reminder {title} on {date}",
    )
    result = agent_tools.create_reminder_tool(title="Reorganize emails", date="2026-08-12")
    assert result == "created reminder Reorganize emails on 2026-08-12"


def test_media_control_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agent_tools, "media_control",
        lambda action: seen.update(action=action) or "OK",
    )
    result = agent_tools.media_control_tool(action="mute")
    assert result == "OK"
    assert seen == {"action": "mute"}


def test_set_volume_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agent_tools, "set_volume",
        lambda level: seen.update(level=level) or "OK",
    )
    result = agent_tools.set_volume_tool(level=60)
    assert result == "OK"
    assert seen == {"level": 60}


def test_launch_app_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agent_tools, "launch_app",
        lambda name: seen.update(name=name) or "OK",
    )
    result = agent_tools.launch_app_tool(name="notepad")
    assert result == "OK"
    assert seen == {"name": "notepad"}


def test_list_windows_delegates(monkeypatch):
    monkeypatch.setattr(agent_tools, "list_windows", lambda: "Notepad\nVesper")
    assert agent_tools.list_windows_tool() == "Notepad\nVesper"


def test_focus_window_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agent_tools, "focus_window",
        lambda name: seen.update(name=name) or "OK",
    )
    result = agent_tools.focus_window_tool(name="firefox")
    assert result == "OK"
    assert seen == {"name": "firefox"}


def test_vesper_tools_registers_every_sync_tool():
    """Each @tool adapter must wrap a sync function that's actually
    reachable — this would silently drop a tool if _agent_tools and the
    sync function list above ever diverge."""
    registered_names = {t.name for t in agent_tools._agent_tools}
    expected = {
        "search_vault_tool", "read_note_tool", "append_note_tool", "create_note_tool",
        "write_draft_tool", "write_scratch_tool", "upcoming_events_tool",
        "remember_fact_tool", "forget_fact_tool", "complete_deadline_tool",
        "triage_inbox_tool", "filter_subscriptions_tool", "create_calendar_event_tool",
        "delete_calendar_event_tool", "create_reminder_tool", "upcoming_reminders_tool",
        "media_control_tool", "set_volume_tool", "launch_app_tool",
        "list_windows_tool", "focus_window_tool",
    }
    assert registered_names == expected
