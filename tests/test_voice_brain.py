"""Tests for voice.brain.Brain._turn and Brain._stream_turn_events.

Most tests mock Brain._stream_turn_events directly (mirroring how the old
suite mocked voice.llm.stream_mcp) to exercise _turn()'s sentence-splitting,
history, and audit bookkeeping in isolation. A smaller set exercises
_stream_turn_events itself against fake Claude Agent SDK message objects,
replacing the old NDJSON-parsing coverage now that the SDK's typed
dataclasses stand in for the CLI's raw stream-json lines."""
from __future__ import annotations

import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from voice import brain as brain_mod


class _FakeClient:
    """Stands in for ClaudeSDKClient: query() is a no-op, receive_response()
    replays a canned list of SDK message objects."""

    def __init__(self, messages):
        self._messages = messages

    async def query(self, user_text):
        pass

    async def receive_response(self):
        for message in self._messages:
            yield message


@pytest.fixture
def brain(monkeypatch, tmp_path):
    monkeypatch.setattr("voice.config.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("voice.config.load", lambda: {
        "model": "sonnet", "max_history_turns": 40, "stream_replies": True,
        "stream_min_sentence_chars": 24,
    })
    b = brain_mod.Brain()
    monkeypatch.setattr(b, "_system", "test system prompt")
    yield b
    b.close()


def _stub_connected(brain, monkeypatch, messages):
    """Skip the real connect() call and hand _drive() a fake client that
    replays `messages`."""
    async def fake_ensure_connected():
        brain._client = _FakeClient(messages)
    monkeypatch.setattr(brain, "_ensure_connected", fake_ensure_connected)


def test_turn_yields_text_and_updates_history(brain, monkeypatch):
    def fake_stream(user_text):
        yield {"kind": "text", "text": "Hello there. "}
        yield {"kind": "result", "text": "Hello there.", "usage": {}, "cost_usd": None}
    monkeypatch.setattr(brain, "_stream_turn_events", fake_stream)

    chunks = list(brain.turn("hi", source="text"))

    assert "".join(chunks).strip() == "Hello there."
    assert brain.history[-2] == {"role": "user", "content": "hi"}
    assert brain.history[-1] == {"role": "assistant", "content": "Hello there."}


def test_turn_emits_tool_events_without_appending_to_history(brain, monkeypatch):
    emitted = []
    monkeypatch.setattr(brain_mod, "_emit", lambda event: emitted.append(event))

    def fake_stream(user_text):
        yield {"kind": "tool_call", "name": "mcp__vesper__search_vault_tool", "input": {"query": "x"}}
        yield {"kind": "tool_result", "name": "mcp__vesper__search_vault_tool", "output": "found it"}
        yield {"kind": "text", "text": "Found it."}
        yield {"kind": "result", "text": "Found it.", "usage": {}, "cost_usd": None}

    monkeypatch.setattr(brain, "_stream_turn_events", fake_stream)

    list(brain.turn("search my notes"))

    tool_events = [e for e in emitted if e.get("type") == "tool"]
    assert any(e.get("status") == "start" for e in tool_events)
    assert any(e.get("status") == "done" for e in tool_events)
    # Only one assistant turn persisted — the SDK's internal agentic loop
    # already resolved the tool call before returning.
    assistant_turns = [h for h in brain.history if h["role"] == "assistant"]
    assert len(assistant_turns) == 1
    assert assistant_turns[0]["content"] == "Found it."


def test_turn_handles_empty_response(brain, monkeypatch):
    def fake_stream(user_text):
        return iter(())  # no events at all
    monkeypatch.setattr(brain, "_stream_turn_events", fake_stream)
    before = list(brain.history)
    chunks = list(brain.turn("hi"))
    assert chunks == ["[couldn't get a response — try again]"]
    assert brain.history == before  # user turn popped back off


def test_turn_flushes_trailing_unterminated_fragment(brain, monkeypatch):
    # "First sentence is complete." is >= stream_min_sentence_chars (24), so
    # it gets emitted as its own sentence during the loop (emitted becomes
    # non-empty) before the trailing fragment (no terminal punctuation)
    # is ever seen.
    def fake_stream(user_text):
        yield {"kind": "text", "text": "First sentence is complete. "}
        yield {"kind": "text", "text": "Second incomplete"}
        yield {"kind": "result", "text": "First sentence is complete. Second incomplete",
               "usage": {}, "cost_usd": None}
    monkeypatch.setattr(brain, "_stream_turn_events", fake_stream)

    chunks = list(brain.turn("hi"))
    joined = " ".join(chunks)

    assert "First sentence is complete." in joined
    assert "Second incomplete" in joined


def test_turn_mid_stream_exception_keeps_partial_reply(brain, monkeypatch):
    def fake_stream(user_text):
        yield {"kind": "text", "text": "Partial answer here"}
        raise RuntimeError("stream broke")
    monkeypatch.setattr(brain, "_stream_turn_events", fake_stream)

    chunks = list(brain.turn("hi"))
    joined = " ".join(chunks)

    assert "Partial answer here" in joined
    assert "[couldn't get a response — try again]" not in chunks
    assert brain.history[-1] == {"role": "assistant", "content": "Partial answer here"}


def test_stream_turn_events_translates_text_and_tool_calls(brain, monkeypatch):
    messages = [
        StreamEvent(uuid="u1", session_id="s1", event={
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "I'll search. "},
        }),
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__vesper__search_vault_tool", input={"query": "test"}),
        ], model="claude-x"),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": "found it"}]),
        ]),
        StreamEvent(uuid="u2", session_id="s1", event={
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Done."},
        }),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                      num_turns=1, session_id="s1", result="Done.",
                      usage={"input_tokens": 1}, total_cost_usd=0.01),
    ]
    _stub_connected(brain, monkeypatch, messages)

    events = list(brain._stream_turn_events("search test"))
    kinds = [e["kind"] for e in events]

    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds.index("tool_call") < kinds.index("tool_result")

    tool_call = next(e for e in events if e["kind"] == "tool_call")
    assert tool_call["name"] == "mcp__vesper__search_vault_tool"
    assert tool_call["input"] == {"query": "test"}

    tool_result = next(e for e in events if e["kind"] == "tool_result")
    assert tool_result["name"] == "mcp__vesper__search_vault_tool"
    assert tool_result["output"] == "found it"

    text = "".join(e["text"] for e in events if e["kind"] == "text")
    assert text == "I'll search. Done."

    result = next(e for e in events if e["kind"] == "result")
    assert result["text"] == "Done."
    assert result["cost_usd"] == 0.01

    # ResultMessage.session_id is captured for the next connect()'s resume=.
    assert brain._session_id == "s1"


def test_stream_turn_events_filters_non_vesper_tool_calls(brain, monkeypatch):
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="ts1", name="ToolSearch", input={"query": "x"}),
        ], model="claude-x"),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="ts1", content=[{"type": "text", "text": "irrelevant"}]),
        ]),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                      num_turns=1, session_id="s1", result="Done.", usage={}, total_cost_usd=None),
    ]
    _stub_connected(brain, monkeypatch, messages)

    events = list(brain._stream_turn_events("hi"))
    kinds = [e["kind"] for e in events]

    assert "tool_call" not in kinds
    assert "tool_result" not in kinds
    assert kinds == ["result"]


def test_build_system_includes_delivery_tags_note_for_chatterbox(monkeypatch, tmp_path):
    from datetime import timezone
    monkeypatch.setattr("voice.config.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("voice.config.get_vault_dir", lambda: None)
    monkeypatch.setattr("voice.config.get_timezone", lambda: timezone.utc)
    monkeypatch.setattr("voice.memory.load_context", lambda: "")
    from voice.brain import _build_system

    system = _build_system({"tts_engine": "chatterbox"})

    assert "[sigh]" in system


def test_build_system_omits_delivery_tags_note_for_other_engines(monkeypatch, tmp_path):
    from datetime import timezone
    monkeypatch.setattr("voice.config.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("voice.config.get_vault_dir", lambda: None)
    monkeypatch.setattr("voice.config.get_timezone", lambda: timezone.utc)
    monkeypatch.setattr("voice.memory.load_context", lambda: "")
    from voice.brain import _build_system

    system = _build_system({"tts_engine": "edge"})

    assert "[sigh]" not in system
