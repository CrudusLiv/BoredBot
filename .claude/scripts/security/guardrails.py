"""Deterministic blocklist for tool calls. Called by the PreToolUse hook.

Three verdicts:

- `pass`        -- safe to run, hook returns silent allow.
- `fail`        -- blocked outright; hook returns deny + reason.
- `suspicious`  -- flagged but ambiguous; hook returns ask (user authorizes).

Rules come from USER.md "Hard limits" + the Phase 8 table in the PRD.

This is defense in depth. The first line of defense is integration modules
not exposing send/delete functions at all. If you're adding a rule here for
something that should never have been possible, fix the integration too.
"""
from __future__ import annotations

import re
from typing import Any

# --- Destructive shell / filesystem ---
_DELETE_PATTERNS: list[str] = [
    r"\brm\s+\S",
    r"\bdel\s+\S",
    r"\bRemove-Item\b",
    r"\bgit\s+rm\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.removedirs\b",
    r"\bshutil\.rmtree\b",
    r"\.unlink\(",
    r"\.rmdir\(",
    r"\brmdir\s+\S",
    r"\bDROP\s+TABLE\b",
    r"\bDROP\s+DATABASE\b",
    r"\bTRUNCATE\s+TABLE\b",
]

# --- Hard-to-reverse git ---
_FORCE_GIT_PATTERNS: list[str] = [
    r"\bgit\s+push\b[\s\S]*?--force",
    r"\bgit\s+push\b[\s\S]*?\s-f\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f",
    r"\bgit\s+checkout\s+--\s",
    r"\bgit\s+restore\s+--source",
    # (?-i:-D) keeps this case-sensitive despite the global IGNORECASE in
    # _matches: only the force-delete -D is hard to reverse. The safe -d
    # refuses to drop unmerged branches, so it must not trip this rule.
    r"\bgit\s+branch\s+(?-i:-D)\b",
]

# --- Financial ---
_FINANCIAL_PATTERNS: list[str] = [
    r"\bstripe\.com\b",
    r"\bpaypal\.com\b",
    r"\b(chase|wellsfargo|bankofamerica|citi|hsbc|maybank|cimb)\.com\b",
    r"\.(qif|qfx|ofx)\b",
]

# --- Social media post ---
_SOCIAL_POST_PATTERNS: list[str] = [
    r"\btweet\b",
    r"\bpost_status\b",
    r"\bshare_to_(facebook|instagram|x|linkedin|tiktok)\b",
    r"twitter\.com/.*?status",
]

# --- Outgoing message (defense in depth) ---
_SEND_MESSAGE_PATTERNS: list[str] = [
    r"\bSend-MailMessage\b",
    r"\bsmtplib\.\w*\.?send",
    r"\b(gmail|outlook).*\bsend\b",
    r"\bdiscord.*\bwebhook\b.*\bsend\b",
]

ALL_RULES: list[tuple[str, list[str]]] = [
    ("delete",       _DELETE_PATTERNS),
    ("force_git",    _FORCE_GIT_PATTERNS),
    ("financial",    _FINANCIAL_PATTERNS),
    ("social_post",  _SOCIAL_POST_PATTERNS),
    ("send_message", _SEND_MESSAGE_PATTERNS),
]


def _matches(text: str, patterns: list[str]) -> str | None:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


# Tools whose input is data, not an operation. A Python file legitimately
# mentions os.remove; a doc legitimately quotes "rm -rf". We don't scan
# their input fields. Content-level safety lives at the LLM input boundary
# in sanitize.py.
_DATA_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep"}


def _check_shell(command: str) -> dict:
    if not command:
        return {"verdict": "pass", "rule": None, "reason": ""}

    for rule_name, patterns in ALL_RULES:
        hit = _matches(command, patterns)
        if hit:
            return {
                "verdict": "fail",
                "rule": rule_name,
                "reason": f"shell command matched {rule_name} pattern: {hit}",
            }

    flat = command.lower()
    if "dynamous/memory" in flat or "dynamous\\memory" in flat:
        if re.search(r"\b(rm|del|remove-item|rmdir)\b", command, re.IGNORECASE):
            return {
                "verdict": "fail",
                "rule": "memory_delete",
                "reason": "shell command targets Dynamous/Memory with a delete primitive",
            }

    return {"verdict": "pass", "rule": None, "reason": ""}


def check(tool_name: str, tool_input: Any) -> dict:
    """Return {"verdict": "pass|fail|suspicious", "rule": str|None, "reason": str}.

    Scope: only Bash/PowerShell commands are scanned for destructive
    patterns. Edit/Write/Read tool calls pass through -- file content is
    data, not an operation, and content-level safety is handled by
    `sanitize.py` at the LLM input boundary."""
    if tool_name in _DATA_TOOLS:
        return {"verdict": "pass", "rule": None, "reason": ""}

    if tool_name in ("Bash", "PowerShell"):
        ti = tool_input or {}
        command = ti.get("command", "") or ""
        commands = ti.get("commands") or []
        if commands:
            command = command + "\n" + "\n".join(str(c) for c in commands)
        return _check_shell(command)

    # Unknown tool: pass through. Add an explicit rule above if a new tool
    # is introduced that can perform destructive operations.
    return {"verdict": "pass", "rule": None, "reason": ""}


def second_check(tool_name: str, tool_input: dict | None, deterministic: dict) -> dict:
    """Optional Haiku second-check for a `suspicious` verdict.

    The deterministic layer currently only emits pass/fail, so this is wired
    but unused. Kept for future expansion (e.g. if we add a heuristic-but-
    -ambiguous rule). On any error we return the deterministic verdict
    unchanged -- never block on LLM availability."""
    if deterministic.get("verdict") != "suspicious":
        return deterministic
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from core import llm  # type: ignore
    except ImportError:
        return deterministic
    if not llm.is_available():
        return deterministic
    prompt = (
        f"Tool: {tool_name}\nInput: {tool_input}\n"
        f"Initial flag: {deterministic.get('reason')}\n\n"
        "Is this tool call genuinely destructive, financial, or sending a "
        "message on the user's behalf? Reply with one word: PASS, FAIL."
    )
    try:
        out = (llm.call(prompt, model="haiku", task="security_guard", timeout=30) or "").strip().upper()
    except Exception:
        return deterministic
    if out.startswith("PASS"):
        return {"verdict": "pass", "rule": None, "reason": "llm overrode suspicion"}
    if out.startswith("FAIL"):
        return {"verdict": "fail", "rule": deterministic.get("rule"), "reason": "llm confirmed"}
    return deterministic
