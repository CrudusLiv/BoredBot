"""RETIRED — kept for history, not collected for anything meaningful.

voice.llm.stream_mcp() (and the claude -p subprocess it drove) is removed;
voice/brain.py now talks to the Claude Agent SDK directly. See
tests/test_voice_brain.py for the equivalent event-stream coverage against
Brain._stream_turn_events()."""
from __future__ import annotations
