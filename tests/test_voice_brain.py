"""Tests for voice.brain.Brain._turn against voice.llm.stream_mcp, replacing
the old regex tool-protocol tests (there were none — this is new coverage
for previously-untested code)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from voice import brain as brain_mod


@pytest.fixture
def brain(monkeypatch, tmp_path):
    monkeypatch.setattr("voice.config.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("voice.config.load", lambda: {
        "model": "sonnet", "max_history_turns": 40, "stream_replies": True,
        "stream_min_sentence_chars": 24,
    })
    monkeypatch.setattr("voice.tools.REGISTRY", [])
    monkeypatch.setattr("voice.tools.dispatch", lambda name, args: "")
    monkeypatch.setattr("voice.tools._tool_descriptions", lambda: "")
    b = brain_mod.Brain()
    monkeypatch.setattr(b, "_system", "test system prompt")
    return b


def test_turn_yields_text_and_updates_history(brain, monkeypatch):
    def fake_stream_mcp(prompt, **kw):
        yield {"kind": "text", "text": "Hello there. "}
        yield {"kind": "result", "text": "Hello there.", "usage": {}, "cost_usd": None}
    monkeypatch.setattr("voice.llm.stream_mcp", fake_stream_mcp)

    chunks = list(brain.turn("hi", source="text"))

    assert "".join(chunks).strip() == "Hello there."
    assert brain.history[-2] == {"role": "user", "content": "hi"}
    assert brain.history[-1] == {"role": "assistant", "content": "Hello there."}


def test_turn_emits_tool_events_without_appending_to_history(brain, monkeypatch):
    emitted = []
    monkeypatch.setattr(brain_mod, "_emit", lambda event: emitted.append(event))

    def fake_stream_mcp(prompt, **kw):
        yield {"kind": "tool_call", "name": "mcp__vesper__search_vault_tool", "input": {"query": "x"}}
        yield {"kind": "tool_result", "name": "mcp__vesper__search_vault_tool", "output": "found it"}
        yield {"kind": "text", "text": "Found it."}
        yield {"kind": "result", "text": "Found it.", "usage": {}, "cost_usd": None}

    monkeypatch.setattr("voice.llm.stream_mcp", fake_stream_mcp)

    list(brain.turn("search my notes"))

    tool_events = [e for e in emitted if e.get("type") == "tool"]
    assert any(e.get("status") == "start" for e in tool_events)
    assert any(e.get("status") == "done" for e in tool_events)
    # Only one assistant turn persisted — the CLI's internal agentic loop
    # already resolved the tool call before returning.
    assistant_turns = [h for h in brain.history if h["role"] == "assistant"]
    assert len(assistant_turns) == 1
    assert assistant_turns[0]["content"] == "Found it."


def test_turn_handles_empty_response(brain, monkeypatch):
    def fake_stream_mcp(prompt, **kw):
        return iter(())  # no events at all — subprocess produced nothing
    monkeypatch.setattr("voice.llm.stream_mcp", fake_stream_mcp)
    before = list(brain.history)
    chunks = list(brain.turn("hi"))
    assert chunks == ["[couldn't get a response — try again]"]
    assert brain.history == before  # user turn popped back off


def test_turn_flushes_trailing_unterminated_fragment(brain, monkeypatch):
    # "First sentence is complete." is >= stream_min_sentence_chars (24), so
    # it gets emitted as its own sentence during the loop (emitted becomes
    # non-empty) before the trailing fragment (no terminal punctuation)
    # is ever seen.
    def fake_stream_mcp(prompt, **kw):
        yield {"kind": "text", "text": "First sentence is complete. "}
        yield {"kind": "text", "text": "Second incomplete"}
        yield {"kind": "result", "text": "First sentence is complete. Second incomplete",
               "usage": {}, "cost_usd": None}
    monkeypatch.setattr("voice.llm.stream_mcp", fake_stream_mcp)

    chunks = list(brain.turn("hi"))
    joined = " ".join(chunks)

    assert "First sentence is complete." in joined
    assert "Second incomplete" in joined


def test_turn_mid_stream_exception_keeps_partial_reply(brain, monkeypatch):
    def fake_stream_mcp(prompt, **kw):
        yield {"kind": "text", "text": "Partial answer here"}
        raise RuntimeError("stream broke")
    monkeypatch.setattr("voice.llm.stream_mcp", fake_stream_mcp)

    chunks = list(brain.turn("hi"))
    joined = " ".join(chunks)

    assert "Partial answer here" in joined
    assert "[couldn't get a response — try again]" not in chunks
    assert brain.history[-1] == {"role": "assistant", "content": "Partial answer here"}
