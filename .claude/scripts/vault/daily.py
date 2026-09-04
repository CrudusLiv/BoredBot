"""Single writer for the daily vault note."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_BLOCK_RE = re.compile(
    r"<!-- timeline:begin -->\n## Timeline\n(?P<nav>.*?)\n<!-- timeline:end -->",
    re.DOTALL,
)


def _daily_dir() -> Path:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return project_dir / "Dynamous" / "Memory" / "daily"


def _ts() -> str:
    return datetime.now().strftime("%H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _prev_daily(daily_dir: Path, day: str) -> str | None:
    """Newest existing daily-note date strictly before `day` (file order, not calendar)."""
    earlier = sorted(
        p.stem for p in daily_dir.glob("*.md") if _DATE_RE.match(p.name) and p.stem < day
    )
    return earlier[-1] if earlier else None


def _timeline_block(prev: str | None, nxt: str | None) -> str:
    parts = []
    if prev:
        parts.append(f"← [[{prev}]]")
    if nxt:
        parts.append(f"[[{nxt}]] →")
    nav = " · ".join(parts)
    return f"<!-- timeline:begin -->\n## Timeline\n{nav}\n<!-- timeline:end -->"


def _add_forward_link(path: Path, day: str) -> None:
    """Point an existing daily note's timeline block forward to `day`.

    Keeps the graph chain unbroken: the note that was newest before today gains a
    `next` link to today. Idempotent -- a no-op if the link is already there.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    m = _BLOCK_RE.search(text)
    fwd = f"[[{day}]] →"
    if m:
        if day in m.group("nav"):
            return
        nav = re.sub(r"\s*·?\s*\[\[[^\]]+\]\] →\s*$", "", m.group("nav")).rstrip()
        nav = f"{nav} · {fwd}" if nav else fwd
        block = f"<!-- timeline:begin -->\n## Timeline\n{nav}\n<!-- timeline:end -->"
        new_text = text[: m.start()] + block + text[m.end() :]
    else:
        block = _timeline_block(_prev_daily(path.parent, path.stem), day)
        lines = text.split("\n")
        if lines and lines[0].startswith("# "):
            rest = "\n".join(lines[1:]).lstrip("\n")
            new_text = f"{lines[0]}\n\n{block}\n" + (f"\n{rest}" if rest else "")
        else:
            new_text = f"{block}\n\n{text}"
    path.write_text(new_text, encoding="utf-8")


def _create_daily(target: Path, day: str) -> None:
    """Create `day`'s note with a header + timeline nav block, and link yesterday forward."""
    prev = _prev_daily(target.parent, day)
    target.write_text(f"# {day}\n\n{_timeline_block(prev, None)}\n", encoding="utf-8")
    if prev:
        _add_forward_link(target.parent / f"{prev}.md", day)


def append_line(line: str) -> None:
    """Append one timestamped line to today's daily note.
    Creates the file with a # YYYY-MM-DD header + timeline block if it doesn't exist."""
    daily_dir = _daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)
    today = _today()
    target = daily_dir / f"{today}.md"
    created = not target.exists()
    if created:
        _create_daily(target, today)
    entry = f"[{_ts()}] {line}\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(f"\n{entry}" if created else entry)


def append_block(label: str, content: str) -> None:
    """Append a ## [HH:MM] <label> header + content block.
    Used by session-flush hooks. Preserves existing daily note format."""
    daily_dir = _daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)
    today = _today()
    target = daily_dir / f"{today}.md"
    created = not target.exists()
    if created:
        _create_daily(target, today)
    sep = "\n" if created else "\n\n"
    block = f"{sep}## [{_ts()}] {label}\n\n{content}\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(block)


def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="vault/daily.py")
    sub = parser.add_subparsers(dest="cmd")

    com = sub.add_parser("commit")
    com.add_argument("kind", choices=["work", "personal"])
    com.add_argument("repo")
    com.add_argument("message")

    alr = sub.add_parser("alert")
    alr.add_argument("title")
    alr.add_argument("body")

    args = parser.parse_args()
    if args.cmd == "commit":
        append_line(f"Commit [{args.kind}]: {args.repo} — {args.message}")
    elif args.cmd == "alert":
        append_line(f"Alert: {args.title} — {args.body}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli()
