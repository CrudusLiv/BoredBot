"""Shared helpers for the Second Brain hook scripts.

Three lifecycle hooks reuse the same vault paths, transcript parser, Claude
distillation call, and daily-log append logic. Keep this module dependency-free
beyond the standard library (anthropic is imported lazily inside the distill
function so hooks still run when it isn't installed).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
VAULT = PROJECT_DIR / "Dynamous" / "Memory"
DAILY_DIR = VAULT / "daily"

import sys as _sys
_sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

MAX_CONTEXT_CHARS = 16000
MAX_TRANSCRIPT_CHARS = 80000

DISTILL_PROMPT = """You are reviewing a Claude Code session transcript before context is dropped.
Extract only durable items worth remembering tomorrow. Be ruthless — most chatter is not durable.

Use these exact headers, omit any header with no items:

### Decisions
- one line each, with rationale if given

### Lessons
- what worked, what failed, what to do differently next time

### Facts
- non-obvious things discovered about the project, codebase, or external systems

### Open todos
- things the user asked for or implied but that were not finished

If nothing durable happened in this session, output exactly: `_(no durable items)_`
No preamble, no commentary, no closing remarks."""


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def recent_daily_logs(n: int = 3) -> str:
    if not DAILY_DIR.exists():
        return ""
    today = datetime.now()
    blocks: list[str] = []
    for i in range(n):
        d = today - timedelta(days=i)
        path = DAILY_DIR / f"{d.strftime('%Y-%m-%d')}.md"
        if path.exists():
            blocks.append(f"### {path.name}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(blocks)


def build_session_context() -> str:
    """Pack SOUL + USER + MEMORY + DEADLINES + PROJECTS + last 3 daily logs into one context block."""
    parts: list[str] = []
    for label, fname in (
        ("SOUL", "SOUL.md"),
        ("USER", "USER.md"),
        ("MEMORY", "MEMORY.md"),
        ("DEADLINES", "DEADLINES.md"),
        ("PROJECTS", "PROJECTS.md"),
    ):
        body = safe_read(VAULT / fname)
        if body:
            parts.append(f"## {label}\n\n{body}")
    daily = recent_daily_logs(3)
    if daily:
        parts.append(f"## Recent daily logs (last 3 days)\n\n{daily}")
    text = "\n\n---\n\n".join(parts)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS] + "\n\n[truncated]"
    return text


def parse_transcript(path: Path) -> str:
    """Flatten a Claude Code JSONL transcript into role-tagged plain text.

    Defensive against multiple shapes — entries may be `{role, content}` or
    `{type, message: {role, content}}`, and content may be a string or a list
    of typed parts (text / tool_use / tool_result).
    """
    if not path or not path.exists():
        return ""
    out: list[str] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") if isinstance(entry.get("message"), dict) else entry
            role = msg.get("role") or entry.get("type")
            content = msg.get("content", "")
            if isinstance(content, list):
                pieces: list[str] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text":
                        pieces.append(part.get("text", ""))
                    elif ptype == "tool_use":
                        pieces.append(f"[tool_use: {part.get('name', '?')}]")
                    elif ptype == "tool_result":
                        result = part.get("content", "")
                        if isinstance(result, list):
                            result = " ".join(p.get("text", "") for p in result if isinstance(p, dict))
                        pieces.append(f"[tool_result: {str(result)[:200]}]")
                content = " ".join(p for p in pieces if p)
            if role and content:
                out.append(f"{str(role).upper()}: {content}")
    return "\n".join(out)


def distill_with_claude(transcript_text: str) -> str:
    """Extract durable items from a transcript. Tries the `claude -p` CLI first
    (uses the user's Claude Code login), falls back to the Anthropic SDK if the
    CLI isn't on PATH. Hooks must never crash a session, so all errors degrade
    to a `_(skipped)_` marker rather than raising."""
    if not transcript_text.strip():
        return "_(empty transcript)_"
    if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
        transcript_text = "[earlier truncated]\n" + transcript_text[-MAX_TRANSCRIPT_CHARS:]

    # Path 1: claude -p CLI (preferred — no API key needed)
    try:
        import sys
        sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts" / "heartbeat"))
        import llm  # type: ignore
        if llm.is_available():
            text = llm.call(transcript_text, system_prompt=DISTILL_PROMPT, model="haiku")
            if text:
                return text
    except Exception:
        pass  # fall through to SDK

    # Path 2: Anthropic SDK fallback
    try:
        from anthropic import Anthropic
    except ImportError:
        return "_(distillation skipped: `claude` CLI not on PATH and `pip install anthropic` not run)_"
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "_(distillation skipped: `claude` CLI not on PATH and ANTHROPIC_API_KEY not set)_"
    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=DISTILL_PROMPT,
            messages=[{"role": "user", "content": transcript_text}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        return text.strip() or "_(empty distillation)_"
    except Exception as exc:
        return f"_(distillation failed: {type(exc).__name__}: {exc})_"


def append_to_daily(content: str, label: str) -> None:
    from vault.daily import append_block
    append_block(label, content)


def read_stdin_payload() -> dict:
    import sys
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}


_EMPTY_DISTILL_PREFIXES = (
    "_(empty transcript)",
    "_(empty distillation)",
    "_(no durable items)",
    "_(distillation skipped",
    "_(distillation failed",
)


def flush_to_daily(label_prefix: str) -> None:
    """Shared body of session-end and pre-compact hooks.

    Parses the transcript referenced by stdin, distills durable items, and
    appends to today's daily log -- but only when there is something worth
    recording. Bails silently (with a stderr breadcrumb for debugging) if:

    - payload has no `transcript_path`
    - path doesn't point to a file
    - parse_transcript raises
    - the parsed transcript is empty
    - the distilled output is one of the empty-/no-durable-items markers

    This keeps the daily log free of useless stubs from sessions that exit
    before any work happens (the matchers `prompt_input_exit` / `other`
    fire frequently in those cases).
    """
    import sys

    payload = read_stdin_payload()
    raw_path = payload.get("transcript_path") or ""
    reason = payload.get("reason") or "unknown"

    if not raw_path:
        print(f"[{label_prefix}] skipped: no transcript_path in payload", file=sys.stderr)
        return

    path = Path(raw_path)
    if not path.is_file():
        print(f"[{label_prefix}] skipped: transcript not a file: {path}", file=sys.stderr)
        return

    try:
        transcript_text = parse_transcript(path)
    except OSError as exc:
        print(f"[{label_prefix}] parse failed for {path}: {exc}", file=sys.stderr)
        return

    if not transcript_text.strip():
        print(f"[{label_prefix}] skipped: empty transcript {path}", file=sys.stderr)
        return

    distilled = distill_with_claude(transcript_text)
    stripped = distilled.strip().lower()
    if not stripped or stripped.startswith(_EMPTY_DISTILL_PREFIXES):
        print(f"[{label_prefix}] skipped: {distilled.strip()[:80] or 'no output'}", file=sys.stderr)
        return

    append_to_daily(distilled, label=f"{label_prefix} ({reason})")
