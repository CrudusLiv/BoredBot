# voice/avatar_emotion.py
"""Pure state->emotion classifier for the avatar's face (voice/static/avatar/
expressions.js). Hooked into ui_server.post_event() so every existing `state`
event (idle/listening/thinking/speaking/error, already emitted by brain.py
and main.py) also drives an `emotion` event -- no changes to the brain or
turn loop needed.

Deliberately state-based, not content-based: a full emotion set tied to
reply sentiment/content is out of scope (spec's Non-goals) pending a
personality/voice rewrite that hasn't happened yet."""
from __future__ import annotations

_EMOTION_MAP: dict[str, tuple[str, float]] = {
    "thinking": ("focused", 0.7),
    "speaking": ("pleased", 0.6),
    "listening": ("neutral", 0.3),
    "idle": ("neutral", 0.2),
    "error": ("neutral", 0.2),
}


def classify(state: str) -> dict | None:
    """Return an {"type": "emotion", ...} event for a given `state` value,
    or None if the state has no mapped emotion."""
    mapped = _EMOTION_MAP.get(state)
    if mapped is None:
        return None
    tag, intensity = mapped
    return {"type": "emotion", "tag": tag, "intensity": intensity}
