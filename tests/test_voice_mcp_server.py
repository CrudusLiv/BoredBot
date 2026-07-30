"""Tests for voice.mcp_server's tool wrappers: each must still reach the
exact same underlying function, and confirmation-gated tools must still
block on voice.safety.confirm_with_reason before running."""
from __future__ import annotations

import pytest

from voice import mcp_server


def test_search_vault_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        mcp_server, "search_vault",
        lambda query, top_k=5: seen.update(query=query, top_k=top_k) or "OK",
    )
    result = mcp_server.search_vault_tool(query="deadlines", top_k=3)
    assert result == "OK"
    assert seen == {"query": "deadlines", "top_k": 3}


def test_upcoming_events_delegates(monkeypatch):
    monkeypatch.setattr(mcp_server, "upcoming_events", lambda days=7: f"{days} days")
    assert mcp_server.upcoming_events_tool(days=14) == "14 days"


@pytest.mark.parametrize("tool_fn_name,wrapper_name,arg_name,arg_value", [
    ("append_note", "append_note_tool", "path", "x.md"),
    ("create_note", "create_note_tool", "path", "y.md"),
    ("forget", "forget_fact_tool", "key", "some-key"),
    ("complete_deadline", "complete_deadline_tool", "query", "renew passport"),
])
def test_confirmation_gated_tools_block_on_confirm(
    monkeypatch, tool_fn_name, wrapper_name, arg_name, arg_value,
):
    monkeypatch.setattr(mcp_server, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        mcp_server, "confirm_with_reason",
        lambda name, args: (False, "cancelled"),
    )
    underlying_called = []
    monkeypatch.setattr(
        mcp_server, tool_fn_name, lambda **kw: underlying_called.append(kw),
    )
    wrapper = getattr(mcp_server, wrapper_name)
    kwargs = {arg_name: arg_value}
    if wrapper_name in ("append_note_tool", "create_note_tool"):
        kwargs["text"] = "body"
    result = wrapper(**kwargs)
    assert underlying_called == []
    assert result == "[cancelled by user]"


def test_confirmation_approved_runs_underlying_tool(monkeypatch):
    monkeypatch.setattr(mcp_server, "requires_confirmation", lambda name: True)
    monkeypatch.setattr(
        mcp_server, "confirm_with_reason", lambda name, args: (True, "user"),
    )
    monkeypatch.setattr(
        mcp_server, "create_note", lambda path, text: f"created {path}",
    )
    result = mcp_server.create_note_tool(path="z.md", text="hi")
    assert result == "created z.md"


def test_non_gated_tool_never_calls_confirm(monkeypatch):
    called = []
    monkeypatch.setattr(
        mcp_server, "confirm_with_reason", lambda *a: called.append(1),
    )
    monkeypatch.setattr(mcp_server, "requires_confirmation", lambda name: False)
    monkeypatch.setattr(mcp_server, "search_vault", lambda query, top_k=5: "OK")
    mcp_server.search_vault_tool(query="x")
    assert called == []
