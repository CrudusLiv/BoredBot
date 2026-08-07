#!/usr/bin/env python3
"""PreToolUse hook -- runs guardrails.check before every tool invocation.

Stdin payload (Claude Code):
    {
      "session_id": "...",
      "hook_event_name": "PreToolUse",
      "tool_name": "Bash",
      "tool_input": {"command": "...", ...},
      ...
    }

Verdict mapping:
    pass        -> exit 0, no output (silent allow)
    fail        -> exit 0 with permissionDecision=deny + reason (block)
    suspicious  -> exit 0 with permissionDecision=ask  (user authorizes)

We never exit non-zero -- always emit a JSON decision so the user sees *why*
something was blocked. Hooks must never crash the session.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return 0  # never block on malformed stdin

    try:
        from security import guardrails
    except ImportError:
        return 0  # never block if guardrails import fails

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    try:
        verdict = guardrails.check(tool_name, tool_input)
    except Exception as exc:
        print(f"[pre-tool-use-guard] check failed: {exc}", file=sys.stderr)
        return 0

    v = verdict.get("verdict")
    if v == "pass":
        return 0

    decision = "deny" if v == "fail" else "ask"
    reason_prefix = "Phase 8 guardrail" if v == "fail" else "Guardrail flagged"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason":
                f"{reason_prefix} [{verdict.get('rule')}]: {verdict.get('reason')}",
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
