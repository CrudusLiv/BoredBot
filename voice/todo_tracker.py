"""Dynamous/Memory/TODO.md checkbox parser — the minimal todo convention
this repo didn't previously have. Format: `- [ ] task` / `- [x] task`,
same style as HABITS.md's pillar checkboxes."""
from __future__ import annotations

import re
from pathlib import Path

_CHECKBOX_RE = re.compile(r"^- \[([ xX])\]\s+(.+)$", re.MULTILINE)


def _rows(vault_dir: Path) -> list[tuple[bool, str]]:
    p = vault_dir / "TODO.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    return [(m.group(1).lower() == "x", m.group(2).strip()) for m in _CHECKBOX_RE.finditer(text)]


def unchecked_todos(vault_dir: Path) -> list[str]:
    return [text for done, text in _rows(vault_dir) if not done]


def todo_count(vault_dir: Path) -> tuple[int, int]:
    rows = _rows(vault_dir)
    done = sum(1 for d, _ in rows if d)
    return done, len(rows)
