"""One-shot vision call for the screen-read feature -- isolated from
voice/brain.py's persistent conversation session so screenshots never
consume the main session's context budget or bleed into later turns.

Uses claude_agent_sdk.query() (the SDK's stateless one-shot helper) rather
than ClaudeSDKClient, authenticated through the same Max-plan OAuth session
as the rest of the app -- no separate API key.
"""
from __future__ import annotations

import asyncio
import base64
from typing import AsyncIterator, Iterator

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, StreamEvent, query

_INSTRUCTION = (
    "Look at the attached screenshot(s) and respond to whatever is most "
    "relevant -- explain an error, answer a visible question, or give a "
    "short summary if nothing specific stands out. Keep it concise. "
    "Plain text only, no markdown formatting."
)

_OPTIONS = ClaudeAgentOptions(
    system_prompt="Respond in plain text only, no markdown formatting, be concise.",
    allowed_tools=[],
    mcp_servers={},
    strict_mcp_config=True,
    setting_sources=[],
)


def _build_prompt(images: list[bytes]) -> dict:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image).decode("ascii"),
            },
        }
        for image in images
    ]
    content.append({"type": "text", "text": _INSTRUCTION})
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
        "session_id": "",
    }


async def _prompt_stream(images: list[bytes]) -> AsyncIterator[dict]:
    yield _build_prompt(images)


async def _ask_async(images: list[bytes]) -> AsyncIterator[dict]:
    async for message in query(prompt=_prompt_stream(images), options=_OPTIONS):
        if isinstance(message, StreamEvent):
            inner = message.event
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"kind": "text", "text": delta["text"]}
        elif isinstance(message, ResultMessage):
            yield {"kind": "result", "text": message.result or ""}


def ask_about_images(images: list[bytes]) -> Iterator[dict]:
    """Blocks the calling thread while streaming -- call from
    screen_read_hotkeys.py's own thread, never voice/main.py's loop."""
    if not images:
        return
    loop = asyncio.new_event_loop()
    try:
        agen = _ask_async(images)
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.close()
