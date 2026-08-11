"""Tests for voice/screen_read.py::ask_about_images. claude_agent_sdk.query
is mocked -- these tests never make a real network/CLI call."""
from __future__ import annotations

from claude_agent_sdk import ResultMessage, StreamEvent

from voice import screen_read


class _FakeStreamEvent(StreamEvent):
    def __init__(self, event: dict):
        self.event = event
        self.uuid = "u1"
        self.session_id = "s1"


def _text_delta_event(text: str) -> _FakeStreamEvent:
    return _FakeStreamEvent({
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": text},
    })


def test_ask_about_images_streams_text_then_result(monkeypatch):
    async def fake_query(*, prompt, options=None):
        yield _text_delta_event("Hello ")
        yield _text_delta_event("world")
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id="s1",
            total_cost_usd=None, usage={}, result="Hello world",
        )

    monkeypatch.setattr(screen_read, "query", fake_query)

    events = list(screen_read.ask_about_images([b"fakepng"]))

    assert events[0] == {"kind": "text", "text": "Hello "}
    assert events[1] == {"kind": "text", "text": "world"}
    assert events[-1] == {"kind": "result", "text": "Hello world"}


def test_ask_about_images_empty_batch_yields_nothing():
    assert list(screen_read.ask_about_images([])) == []


def test_ask_about_images_sends_base64_image_content(monkeypatch):
    seen = {}

    async def fake_query(*, prompt, options=None):
        async for item in prompt:
            seen["prompt_dict"] = item
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id="s1",
            total_cost_usd=None, usage={}, result="done",
        )

    monkeypatch.setattr(screen_read, "query", fake_query)

    list(screen_read.ask_about_images([b"\x89PNG..."]))

    content = seen["prompt_dict"]["message"]["content"]
    image_blocks = [c for c in content if c["type"] == "image"]
    text_blocks = [c for c in content if c["type"] == "text"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert len(text_blocks) == 1
