"""Cross-session memory file loader/curator.

Loaded into the chat handler's system prompt alongside SOUL/USER/MEMORY.
Written to by (a) explicit user "remember that…" requests routed through
the action layer and (b) the daily-reflection job in memory_reflect.py.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
ABOUT_PATH = PROJECT_DIR / "Dynamous" / "Memory" / "ABOUT.md"

_HEADER = "# About CrudusLiv\n\n(Curated by the daily-reflection job. Manual edits welcome.)\n"


def load_about() -> str:
    """Return ABOUT.md contents, or empty string if missing."""
    if not ABOUT_PATH.exists():
        return ""
    return ABOUT_PATH.read_text(encoding="utf-8")


def append_bullet(fact: str) -> bool:
    """Append `fact` as a `- ` bullet. Creates file if missing. Dedupes
    against existing exact bullets. Returns True if appended, False if dup."""
    fact = fact.strip()
    if not fact:
        return False
    bullet = f"- {fact}"

    if not ABOUT_PATH.exists():
        ABOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ABOUT_PATH.write_text(_HEADER, encoding="utf-8")

    existing = ABOUT_PATH.read_text(encoding="utf-8")
    if bullet in existing.splitlines():
        return False

    suffix = "" if existing.endswith("\n") else "\n"
    ABOUT_PATH.write_text(existing + suffix + bullet + "\n", encoding="utf-8")
    return True
