"""Promote heartbeat-extracted deadlines into DEADLINES.md `## Active`.

Format: `- YYYY-MM-DD — <course/source> — <title>`. Dedup is line-content
match — the source file already moved to inbox/_processed/, so the same
item can't be re-extracted on subsequent ticks."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
DEADLINES = PROJECT_DIR / "Dynamous" / "Memory" / "DEADLINES.md"

SECTION = "## Active"
NEXT_HEADER_RE = re.compile(r"\n## ", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"^_\(.*?\)_\s*$", re.MULTILINE)
SRC_RE = re.compile(r"<!--\s*src:([^>]+?)\s*-->")


def _format_line(item: dict) -> str | None:
    due = (item.get("due_date") or "").strip()
    title = (item.get("title") or "").strip()
    course = (item.get("course") or item.get("source") or "").strip()
    if not due or not title:
        return None
    try:
        date.fromisoformat(due)
    except ValueError:
        return None
    # Visible format only -- no trailing HTML comment. Dedup falls back to
    # line-content match in promote(); good enough since the same source
    # file can only be processed once (it moves to inbox/_processed/).
    return f"- {due} — {course or 'unknown'} — {title}"


def _existing_srcs(section_text: str) -> set[str]:
    return set(SRC_RE.findall(section_text))


def promote(items: list[dict]) -> int:
    """Append unique deadline items into DEADLINES.md `## Active`. Returns count added."""
    if not items or not DEADLINES.exists():
        return 0
    text = DEADLINES.read_text(encoding="utf-8")
    if SECTION not in text:
        return 0

    start = text.index(SECTION)
    rest = text[start + len(SECTION):]
    next_match = NEXT_HEADER_RE.search(rest)
    end = start + len(SECTION) + (next_match.start() if next_match else len(rest))
    section = text[start:end]
    after = text[end:]

    body = section[len(SECTION):]
    body_clean = PLACEHOLDER_RE.sub("", body).rstrip()

    seen = _existing_srcs(body_clean)
    added: list[str] = []
    for item in items:
        line = _format_line(item)
        if not line:
            continue
        src = item.get("source") or ""
        if src and src in seen:
            continue
        if line in body_clean:
            continue
        added.append(line)
        if src:
            seen.add(src)

    if not added:
        return 0

    new_section = SECTION + "\n\n" + (body_clean.lstrip("\n") + "\n" if body_clean.strip() else "") + "\n".join(added) + "\n"
    new_text = text[:start] + new_section + ("\n" + after.lstrip("\n") if after else "")
    DEADLINES.write_text(new_text, encoding="utf-8")
    return len(added)
