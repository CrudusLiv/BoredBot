#!/usr/bin/env python3
"""UserPromptSubmit hook -- capture 'note ...' messages to today's daily log.

If the user's prompt starts with 'note' (case-insensitive), the note body is
appended to today's daily log immediately, before the agent sees the message.
The returned additionalContext tells the agent to reply only 'Added.' so no
rambling confirmation is generated.

Supported formats:
    note test 3
    note: test 3
    note — test 3
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import append_to_daily, read_stdin_payload  # noqa: E402

_NOTE_RE = re.compile(r"^note[:\s\-–—]+(.+)", re.IGNORECASE | re.DOTALL)


def main() -> int:
    payload = read_stdin_payload()
    prompt: str = (payload.get("prompt") or "").strip()

    m = _NOTE_RE.match(prompt)
    if not m:
        return 0  # not a note — let the message through unchanged

    body = m.group(1).strip()
    if not body:
        return 0

    try:
        append_to_daily(body, label="Note")
        captured = True
    except Exception as exc:
        print(f"[note-capture] write failed: {exc}", file=sys.stderr)
        captured = False

    status = "Added." if captured else "Not added (write failed — check stderr)."
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"HOOK: note already written to vault. "
                f"Reply with exactly one word: '{status}' — no other text."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
