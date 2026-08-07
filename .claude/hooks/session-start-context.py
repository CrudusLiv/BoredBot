#!/usr/bin/env python3
"""SessionStart hook — inject vault context into every Claude Code session.

Reads SOUL.md + USER.md + MEMORY.md + the last 3 daily logs and returns them
via `hookSpecificOutput.additionalContext`. Runs on startup, resume, clear,
and compact — the agent always boots with full vault context."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import build_session_context, read_stdin_payload  # noqa: E402


def main() -> None:
    read_stdin_payload()
    context = build_session_context()
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
