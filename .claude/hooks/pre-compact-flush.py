#!/usr/bin/env python3
"""PreCompact hook -- distill the transcript before compaction discards it.

Reads the full session transcript via the path provided in stdin, asks
Haiku to extract durable decisions/lessons/facts/todos, and appends the
result to today's daily log. Skips writing when the distillation has
nothing durable, so the log doesn't grow with empty stubs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import flush_to_daily  # noqa: E402


def main() -> None:
    flush_to_daily("Pre-compact flush")
    sys.exit(0)


if __name__ == "__main__":
    main()
