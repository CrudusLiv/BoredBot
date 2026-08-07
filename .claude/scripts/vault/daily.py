"""Single writer for the daily vault note."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def _daily_dir() -> Path:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return project_dir / "Dynamous" / "Memory" / "daily"


def _ts() -> str:
    return datetime.now().strftime("%H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def append_line(line: str) -> None:
    """Append one timestamped line to today's daily note.
    Creates the file with a # YYYY-MM-DD header if it doesn't exist."""
    daily_dir = _daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)
    today = _today()
    target = daily_dir / f"{today}.md"
    entry = f"[{_ts()}] {line}\n"
    if target.exists():
        with target.open("a", encoding="utf-8") as f:
            f.write(entry)
    else:
        target.write_text(f"# {today}\n\n{entry}", encoding="utf-8")


def append_block(label: str, content: str) -> None:
    """Append a ## [HH:MM] <label> header + content block.
    Used by session-flush hooks. Preserves existing daily note format."""
    daily_dir = _daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)
    today = _today()
    target = daily_dir / f"{today}.md"
    block = f"\n\n## [{_ts()}] {label}\n\n{content}\n"
    if target.exists():
        with target.open("a", encoding="utf-8") as f:
            f.write(block)
    else:
        target.write_text(f"# {today}\n{block}", encoding="utf-8")


def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="vault/daily.py")
    sub = parser.add_subparsers(dest="cmd")

    lec = sub.add_parser("lecture")
    lec.add_argument("course")
    lec.add_argument("topic")
    lec.add_argument("note_path")

    com = sub.add_parser("commit")
    com.add_argument("kind", choices=["assignment", "personal"])
    com.add_argument("repo")
    com.add_argument("message")

    hab = sub.add_parser("habit")
    hab.add_argument("pillar")

    alr = sub.add_parser("alert")
    alr.add_argument("title")
    alr.add_argument("body")

    args = parser.parse_args()
    if args.cmd == "lecture":
        append_line(f"Lecture: {args.course} — {args.topic} → [[{args.note_path}]]")
    elif args.cmd == "commit":
        append_line(f"Commit [{args.kind}]: {args.repo} — {args.message}")
    elif args.cmd == "habit":
        append_line(f"Habit: {args.pillar}")
    elif args.cmd == "alert":
        append_line(f"Alert: {args.title} — {args.body}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli()
