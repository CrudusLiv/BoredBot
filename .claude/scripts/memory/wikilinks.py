"""Sibling-wikilink management. Bidirectional, idempotent.

"Siblings" for a given note = all other .md files in the same parent folder
AND any .md files inside subfolders one level deep. Two levels deep is NOT
a sibling — that would explode the graph in big project trees.

Marker fences delimit the Related block so re-runs replace cleanly:

    <!-- related:begin -->
    ## Related
    - [[other]]
    <!-- related:end -->

The helper writes Related on every sibling reachable from `file_path`, so a
single call produces a fully connected hub. Idempotent: same inputs produce
identical output bytes.
"""
from __future__ import annotations

from pathlib import Path

RELATED_BEGIN = "<!-- related:begin -->"
RELATED_END = "<!-- related:end -->"

# Category roots whose direct subfolders are independent subjects/projects,
# not assessment-like groupings. We DO NOT cross sibling links across these
# boundaries — otherwise `lectures/DIP215/x.md` links to `lectures/Kotlin/y.md`,
# which floods the graph with cross-course noise.
_CATEGORY_ROOTS = {"lectures", "projects", "research"}


def add_sibling_wikilinks(file_path: Path) -> None:
    """Refresh the Related section in `file_path` and every sibling."""
    siblings = _siblings_for(file_path)
    universe = sorted(set(siblings) | {file_path})
    for note in universe:
        others = [p for p in universe if p != note]
        _write_related(note, others)


def _siblings_for(file_path: Path) -> list[Path]:
    """Return same-folder + one-level-deep subfolder .md siblings.

    Excludes `file_path` itself. Order is deterministic (lex by full path)
    so re-runs produce identical output."""
    folder = file_path.parent
    found: set[Path] = set()
    if folder.exists():
        for p in folder.glob("*.md"):
            if p.is_file() and p != file_path:
                found.add(p)
        for sub in folder.iterdir():
            if not sub.is_dir():
                continue
            for p in sub.glob("*.md"):
                if p.is_file() and p != file_path:
                    found.add(p)
    # Also include the parent-folder neighbours of file_path's own subfolder
    # (so a note inside Assessment_2/ sees notes inside Assessment_3/). Skip
    # when grandparent is a category root — see _CATEGORY_ROOTS docstring.
    grandparent = folder.parent
    if (
        grandparent != folder
        and grandparent.exists()
        and grandparent.name not in _CATEGORY_ROOTS
    ):
        for sub in grandparent.iterdir():
            if not sub.is_dir() or sub == folder:
                continue
            for p in sub.glob("*.md"):
                if p.is_file() and p != file_path:
                    found.add(p)
    return sorted(found, key=lambda p: str(p))


def _write_related(note: Path, others: list[Path]) -> None:
    text = note.read_text(encoding="utf-8")
    begin = text.find(RELATED_BEGIN)
    if begin != -1:
        end = text.find(RELATED_END, begin)
        if end != -1:
            text = (text[:begin] + text[end + len(RELATED_END):]).rstrip() + "\n"
    if not others:
        note.write_text(text, encoding="utf-8")
        return
    links = "\n".join(f"- [[{p.stem}]]" for p in others)
    block = f"\n\n{RELATED_BEGIN}\n## Related\n{links}\n{RELATED_END}\n"
    note.write_text(text.rstrip() + block, encoding="utf-8")
