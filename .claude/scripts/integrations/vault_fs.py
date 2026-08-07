"""Vault filesystem integration -- watches Dynamous/Memory/inbox/ for new files.

Phase 5's lecture-summarizer skill calls list_inbox_new() during heartbeat
ticks, processes each file, then calls delete_after_success() to remove it
after verifying the written summary note is valid.
No external auth -- pure local."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
INBOX = PROJECT_DIR / "Dynamous" / "Memory" / "inbox"
PROCESSED = INBOX / "_processed"

SUPPORTED_SUFFIXES = {".pptx", ".pdf", ".ppt", ".png", ".jpg", ".jpeg"}


def list_inbox_new() -> list[Path]:
    if not INBOX.exists():
        return []
    out: list[Path] = []
    for p in INBOX.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if p.name.startswith("."):
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime)


def success_check(note_path: Path) -> bool:
    """Validate a written lecture/project note: file exists, has YAML
    frontmatter that parses, and at least one non-empty content section
    after the frontmatter. Returns True only if all three hold.

    Frontmatter parsing intentionally uses a minimal hand-rolled check
    rather than pulling in PyYAML — we just need to verify the block
    parses as `key: value` lines between `---` fences."""
    if not note_path.is_file():
        return False
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    frontmatter_block = parts[1]
    body = parts[2]
    for line in frontmatter_block.splitlines():
        if line and line[0] in (" ", "\t"):
            # YAML continuation line (block scalar or folded value) — skip.
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-"):
            continue
        if ":" not in stripped:
            return False
        key, value = stripped.split(":", 1)
        if not key or any(c in key for c in " \t"):
            return False
        # Value that starts with ": " indicates malformed YAML (e.g. "key: : bad")
        if value.lstrip().startswith(":"):
            return False
    if not body.strip():
        return False
    return True


def delete_after_success(src: Path, note_path: Path) -> bool:
    """If `note_path` passes success_check, delete `src` and return True.
    Otherwise leave `src` in place and return False (caller logs why).

    Carve-out per CLAUDE.md / SOUL.md: deletion is permitted only when
    `src` lives inside `inbox/_processed/`. Callers outside that path
    are a bug — fail loudly rather than silently expand the carve-out."""
    if not _is_inside_processed(src):
        raise ValueError(f"delete_after_success refuses to touch {src} — not inside inbox/_processed/")
    if not success_check(note_path):
        return False
    try:
        src.unlink()
    except OSError:
        return False
    return True


def _is_inside_processed(path: Path) -> bool:
    parts = path.resolve().parts
    return "inbox" in parts and "_processed" in parts


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py vault")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    sub.add_parser("inbox")
    args = parser.parse_args(argv)
    json_out = args.json

    if args.subcommand == "inbox":
        files = list_inbox_new()
        if json_out:
            print(json.dumps([str(f.relative_to(PROJECT_DIR)).replace("\\", "/") for f in files], indent=2))
        else:
            if not files:
                print("(inbox empty)")
            for f in files:
                size_kb = f.stat().st_size // 1024
                print(f"  {f.name}  ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
