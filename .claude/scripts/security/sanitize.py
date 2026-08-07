"""Defensive helpers for untrusted text reaching the LLM.

Two primitives:

- `wrap_external(text, source)` envelopes external content in
  `<external_text source="...">...</external_text>` tags so the model has a
  clear trust boundary. Strips control chars and defangs nested wrapper
  tags that could prematurely close the envelope.
- `detect_injection(text)` returns a list of flag names for common
  prompt-injection markers. Caller decides what to do with the flags.

Used by `heartbeat.build_prompt()` and `chat/handler.py` wherever Gmail
bodies, Discord messages, GitHub PR descriptions, or vault inbox file
contents land in a prompt.
"""
from __future__ import annotations

import re
import unicodedata

# Patterns scanned in lower-cased text. Names are returned as flags --
# they're not displayed to end users so they can stay terse.
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+((?:all|previous|above|any|the|prior|earlier)\s+)*instructions?", "ignore_instructions"),
    (r"disregard\s+((?:all|previous|above|any|the|prior|earlier)\s+)*(instructions?|system|rules?)", "disregard"),
    (r"^\s*system\s*[:>]\s*", "system_header"),
    (r"<\s*/?\s*(system|external_text|instructions|user|assistant)\b", "tag_injection"),
    (r"```\s*system\b", "code_fence_system"),
    (r"\bjailbreak\b|\bpretend you are\b|\bact as (?:an? )?(admin|root|system)", "roleplay_pivot"),
    (r"\boverride (the )?(safety|guardrails?|rules?)\b", "override_safety"),
]

# Keep tab (0x09), newline (0x0A), carriage return (0x0D); strip the rest.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Tags whose appearance inside untrusted text could close our wrapper or
# open a fake system/user block. We HTML-escape the leading `<` on these.
_DEFANG_TAG_RE = re.compile(
    r"<\s*/?\s*(external_text|system|instructions|user|assistant)\b",
    re.IGNORECASE,
)


def detect_injection(text: str | None) -> list[str]:
    if not text:
        return []
    flags: list[str] = []
    lowered = text.lower()
    for pattern, name in _INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            flags.append(name)
    if _CONTROL_CHARS_RE.search(text):
        flags.append("control_chars")
    # Cf = "Format" (zero-width joiner, RTL marks, etc). A handful is normal
    # in non-Latin scripts; a swarm is usually a hiding attempt.
    zw_count = sum(1 for c in text if unicodedata.category(c) == "Cf")
    if zw_count > 5:
        flags.append("hidden_chars")
    return flags


def wrap_external(text: str | None, source: str) -> str:
    """Envelope external content in a trust-boundary tag. Never raises."""
    cleaned = _CONTROL_CHARS_RE.sub("", str(text or ""))
    cleaned = _DEFANG_TAG_RE.sub(lambda m: m.group(0).replace("<", "&lt;"), cleaned)
    safe_source = re.sub(r"[^a-z0-9_.-]", "_", (source or "unknown").lower())[:32] or "unknown"
    return f'<external_text source="{safe_source}">\n{cleaned}\n</external_text>'
