# tests/test_voice_avatar_emotion.py
"""Tests for the pure state->emotion classifier that drives the avatar's face.

Deliberately trivial and deterministic: thinking reads as focused, speaking
reads as pleased, everything else is neutral. No LLM/content analysis --
see the design decision recorded in docs/superpowers/plans/
2026-08-05-avatar-embodiment.md Task 8 for why."""
from __future__ import annotations

from voice.avatar_emotion import classify


def test_thinking_maps_to_focused():
    assert classify("thinking") == {"type": "emotion", "tag": "focused", "intensity": 0.7}


def test_speaking_maps_to_pleased():
    assert classify("speaking") == {"type": "emotion", "tag": "pleased", "intensity": 0.6}


def test_listening_idle_error_map_to_neutral():
    assert classify("listening")["tag"] == "neutral"
    assert classify("idle")["tag"] == "neutral"
    assert classify("error")["tag"] == "neutral"


def test_unknown_state_returns_none():
    assert classify("bogus") is None
    assert classify("") is None
