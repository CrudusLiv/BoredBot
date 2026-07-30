"""Tests for voice.llm.stream_mcp's NDJSON event parsing. Feeds recorded
stream-json fixtures through the parser without spawning a real subprocess."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from unittest.mock import MagicMock

from voice import llm

# Captured from a live `claude -p ... --output-format stream-json
# --verbose --include-partial-messages` run with no tool call (see this
# plan's "Verified ground truth" section for the source).
_NO_TOOL_CALL_LINES = [
    {"type": "stream_event", "event": {"type": "content_block_delta",
     "index": 1, "delta": {"type": "text_delta", "text": "hello test"}}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello test"}]}},
    {"is_error": False, "result": "hello test",
     "usage": {"input_tokens": 10, "output_tokens": 117},
     "total_cost_usd": 0.0637, "type": "result"},
]


def _fake_popen(lines):
    proc = MagicMock()
    proc.stdout = iter(json.dumps(line) + "\n" for line in lines)
    proc.wait.return_value = 0
    proc.returncode = 0
    return proc


def test_text_delta_and_final_result(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: _fake_popen(_NO_TOOL_CALL_LINES))
    events = list(llm.stream_mcp("say hello test", model="haiku"))
    text_events = [e for e in events if e["kind"] == "text"]
    result_events = [e for e in events if e["kind"] == "result"]
    assert "".join(e["text"] for e in text_events) == "hello test"
    assert len(result_events) == 1
    assert result_events[0]["text"] == "hello test"
    assert result_events[0]["cost_usd"] == 0.0637


def test_malformed_line_is_skipped_not_fatal(monkeypatch):
    def _bad_popen(*a, **k):
        proc = MagicMock()
        proc.stdout = iter(["not json\n", json.dumps(_NO_TOOL_CALL_LINES[-1]) + "\n"])
        proc.wait.return_value = 0
        proc.returncode = 0
        return proc
    monkeypatch.setattr("subprocess.Popen", _bad_popen)
    events = list(llm.stream_mcp("hi", model="haiku"))
    assert events[-1]["kind"] == "result"


# Captured live from a real `claude -p` run against voice/mcp_server.py
# (prompt: "Use the search_vault_tool to search for 'test', then say
# done.", model haiku, --mcp-config pointing at this worktree's
# voice/mcp_server.py, --strict-mcp-config). This CLI/account also runs a
# deferred-tool-lookup layer (the "ToolSearch" meta-tool) before it can
# call any not-yet-loaded MCP tool, so a real turn shows: text delta ->
# ToolSearch tool_use -> ToolSearch tool_result (a `tool_reference` block,
# not a real result) -> the actual mcp__vesper__search_vault_tool tool_use
# -> its tool_result -> final text + result. Verified ground truth:
#   - tool_use lives on a full `{"type": "assistant", ...}` message (not a
#     stream_event), as a content block: {"type": "tool_use", "id": ...,
#     "name": "mcp__vesper__search_vault_tool", "input": {"query": "test"}}
#     -- name is already the fully-qualified mcp__<server>__<tool> form,
#     and input is a complete parsed dict (no partial_json reassembly
#     needed for the assistant-message path).
#   - tool_result lives on a `{"type": "user", ...}` message, as a content
#     block: {"tool_use_id": ..., "type": "tool_result", "content": <str>}
#     -- key is "tool_use_id", NOT "id"; "content" is a JSON-encoded
#     STRING (not a list of content blocks), here
#     '{"result": "Search index not built. Run: py
#     .claude/scripts/memory/memory_index.py"}' -- the {"result": ...}
#     wrapping is FastMCP's auto-wrap for tools whose return type is a
#     bare `str` (all 12 of voice/mcp_server.py's tools return -> str).
_TOOL_CALL_LINES = [
    {"type": "stream_event", "event": {"type": "content_block_delta", "index": 1,
     "delta": {"type": "text_delta", "text": "I'll search the vault."}}},
    # Internal deferred-tool lookup (ToolSearch) -- must NOT surface as a
    # Vesper tool_call/tool_result; its name has no "mcp__" prefix.
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_ts1", "name": "ToolSearch",
         "input": {"query": "select:mcp__vesper__search_vault_tool", "max_results": 1},
         "caller": {"type": "direct"}}]}},
    {"type": "user", "message": {"content": [
        {"tool_use_id": "toolu_ts1", "type": "tool_result",
         "content": [{"type": "tool_reference", "tool_name": "mcp__vesper__search_vault_tool"}]}]}},
    # The real MCP tool call.
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_01MLzHYq8qfTQREUm3dSdEUz",
         "name": "mcp__vesper__search_vault_tool", "input": {"query": "test"},
         "caller": {"type": "direct"}}]}},
    {"type": "user", "message": {"content": [
        {"tool_use_id": "toolu_01MLzHYq8qfTQREUm3dSdEUz", "type": "tool_result",
         "content": "{\"result\": \"Search index not built. Run: py "
                     ".claude/scripts/memory/memory_index.py\"}"}]}},
    {"type": "stream_event", "event": {"type": "content_block_delta", "index": 1,
     "delta": {"type": "text_delta", "text": "Done."}}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
    {"is_error": False, "result": "Done.",
     "usage": {"input_tokens": 28, "output_tokens": 398},
     "total_cost_usd": 0.0382, "type": "result"},
]


def test_tool_call_and_result_events(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: _fake_popen(_TOOL_CALL_LINES))
    events = list(llm.stream_mcp("Use the search_vault_tool to search for 'test'.", model="haiku"))
    kinds = [e["kind"] for e in events]

    # The internal ToolSearch tool_use/tool_result pair must be filtered
    # out entirely -- it is CLI plumbing, not a Vesper tool call.
    tool_call_events = [e for e in events if e["kind"] == "tool_call"]
    tool_result_events = [e for e in events if e["kind"] == "tool_result"]
    assert len(tool_call_events) == 1
    assert len(tool_result_events) == 1

    call = tool_call_events[0]
    assert call["name"] == "mcp__vesper__search_vault_tool"
    assert call["input"] == {"query": "test"}

    result = tool_result_events[0]
    assert result["name"] == "mcp__vesper__search_vault_tool"
    assert result["output"] == (
        "Search index not built. Run: py .claude/scripts/memory/memory_index.py"
    )

    # Ordering: tool_call must precede its tool_result, and the final
    # "result" event must be last and unique.
    assert kinds.index("tool_call") < kinds.index("tool_result")
    assert kinds[-1] == "result"
    assert kinds.count("result") == 1


def test_strict_mcp_config_flag_present(monkeypatch):
    """Without --strict-mcp-config, `claude -p` also tries to connect every
    other globally-configured MCP server (context7, playwright, github, ...)
    alongside vesper, and a fast model turn can race ahead of vesper's own
    stdio handshake finishing -- silently starving the model of Vesper's
    tools with no error surfaced anywhere. --strict-mcp-config restricts
    connection attempts to just the server passed via --mcp-config."""
    captured_cmd = {}

    def _capture_popen(cmd, *a, **k):
        captured_cmd["cmd"] = cmd
        return _fake_popen(_NO_TOOL_CALL_LINES)

    monkeypatch.setattr("subprocess.Popen", _capture_popen)
    list(llm.stream_mcp("say hello test", model="haiku"))
    assert "--strict-mcp-config" in captured_cmd["cmd"]


def test_prompt_sent_via_stdin_not_argv(monkeypatch):
    """A prompt positional argv element overflows Windows' ~32K
    CreateProcess command-line limit once conversation history grows (see
    _call_claude_cli's existing input=prompt stdin pattern -- stream_mcp
    must match it instead of putting the prompt on the command line)."""
    huge_prompt = "x" * 50_000
    captured = {}

    def _capture_popen(cmd, **kwargs):
        proc = _fake_popen(_NO_TOOL_CALL_LINES)
        proc.stdin = MagicMock()
        captured["cmd"] = cmd
        captured["proc"] = proc
        return proc

    monkeypatch.setattr("subprocess.Popen", _capture_popen)
    list(llm.stream_mcp(huge_prompt, model="haiku"))

    assert huge_prompt not in captured["cmd"]
    assert "-p" in captured["cmd"]
    captured["proc"].stdin.write.assert_called_once_with(huge_prompt)
    captured["proc"].stdin.close.assert_called_once()


def test_timeout_expired_kills_process(monkeypatch):
    """If proc.wait(timeout=...) is reached and the process is still late
    (TimeoutExpired), the process must be killed rather than leaking the
    exception / leaving the child running."""
    proc = MagicMock()
    proc.stdout = iter(json.dumps(line) + "\n" for line in _NO_TOOL_CALL_LINES)
    proc.returncode = 0
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="claude", timeout=90), None]
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: proc)

    events = list(llm.stream_mcp("say hello test", model="haiku"))

    assert any(e["kind"] == "result" for e in events)
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2


def test_hanging_stdout_gets_killed_by_watchdog(monkeypatch):
    """A subprocess whose stdout stays open (never hits EOF) would otherwise
    block the `for line in proc.stdout` loop forever, so proc.wait(timeout=...)
    -- which only runs AFTER that loop exits -- would never get a chance to
    apply the timeout. A watchdog timer must kill the process independently
    of the read loop once `timeout` elapses."""
    never_event = threading.Event()

    def _hanging_stdout():
        yield json.dumps(_NO_TOOL_CALL_LINES[0]) + "\n"
        never_event.wait(timeout=5)  # simulates a hang; unblocked by the test
        yield json.dumps(_NO_TOOL_CALL_LINES[-1]) + "\n"

    proc = MagicMock()
    proc.stdout = _hanging_stdout()
    proc.returncode = 0
    proc.wait.return_value = 0
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: proc)

    collected = []

    def _consume():
        collected.extend(llm.stream_mcp("say hello test", model="haiku", timeout=0.05))

    t = threading.Thread(target=_consume, daemon=True)
    t.start()

    # Give the watchdog time to fire (timeout=0.05s) while the generator is
    # still parked on never_event.wait() inside the hanging stdout iterator.
    for _ in range(50):  # up to ~1s
        if proc.kill.called:
            break
        time.sleep(0.02)
    assert proc.kill.called, "watchdog did not kill the hung process in time"

    # Unblock the fake stdout so the consumer thread can finish and the
    # generator's finally block runs cleanly.
    never_event.set()
    t.join(timeout=5)
    assert not t.is_alive()
    assert any(e["kind"] == "result" for e in collected)
