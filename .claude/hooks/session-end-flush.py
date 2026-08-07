#!/usr/bin/env python3
"""SessionEnd hook -- distill the transcript and flush to today's daily log.

Catches sessions that exit without ever triggering compaction. Skips writing
when the transcript is missing/empty/produces no durable items, so the daily
log doesn't fill up with stubs from `prompt_input_exit` and `other` matchers
firing on near-empty sessions."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import flush_to_daily  # noqa: E402


def main() -> None:
    flush_to_daily("Session-end flush")
    sys.exit(0)


if __name__ == "__main__":
    main()
