#!/usr/bin/env python3
"""One-off backfill: run daily reflection over every unprocessed daily log.

Usage:
    py .claude/scripts/backfill_reflect.py [--from YYYY-MM-DD]

Defaults to processing all logs after the last Decisions entry in MEMORY.md
(2026-05-13). Skips any date that already has its marker in MEMORY.md."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

from memory_reflect import MEMORY, DAILY, REFLECT_SYSTEM, _insert_into_section
from core import llm

KL = timezone(timedelta(hours=8))

# Logs up to and including this date have already been manually curated.
DEFAULT_FROM = "2026-05-14"


def _already_present(memory_text: str, date: str) -> bool:
    return date in memory_text


def reflect_for_date(log_date: str) -> dict:
    log_path = DAILY / f"{log_date}.md"
    if not log_path.exists():
        print(f"  [{log_date}] no log, skipping")
        return {}
    log_text = log_path.read_text(encoding="utf-8")
    if not log_text.strip():
        print(f"  [{log_date}] empty log, skipping")
        return {}
    memory = MEMORY.read_text(encoding="utf-8") if MEMORY.exists() else ""
    if not llm.is_available():
        print("  claude CLI not available — aborting", file=sys.stderr)
        sys.exit(1)
    prompt = (
        f"DAILY LOG ({log_date}):\n\n{log_text}\n\n"
        f"---\n\nCURRENT MEMORY.md:\n\n{memory}\n\n"
        f"Return JSON per the schema."
    )
    return llm.call_json(prompt, system_prompt=REFLECT_SYSTEM, model="haiku", task="memory_reflect") or {}


def append_for_date(items: dict, date: str) -> int:
    if not items or not MEMORY.exists():
        return 0
    text = MEMORY.read_text(encoding="utf-8")
    appended = 0
    for section, key in (("Decisions", "new_decisions"), ("Lessons", "new_lessons")):
        new = items.get(key) or []
        text, n = _insert_into_section(text, section, new, date)
        appended += n
    facts = items.get("new_facts") or []
    if facts:
        text, n = _insert_into_section(text, "Lessons", [f"(fact) {f}" for f in facts], date)
        appended += n
    if appended:
        MEMORY.write_text(text, encoding="utf-8")
    return appended


def main() -> int:
    from_date = DEFAULT_FROM
    if "--from" in sys.argv:
        idx = sys.argv.index("--from")
        from_date = sys.argv[idx + 1]

    logs = sorted(DAILY.glob("*.md"))
    to_process = [p for p in logs if p.stem >= from_date]

    if not to_process:
        print("No logs to process.")
        return 0

    print(f"Backfilling {len(to_process)} log(s) from {from_date} onwards...\n")
    total = 0
    for log_path in to_process:
        date = log_path.stem
        memory_text = MEMORY.read_text(encoding="utf-8") if MEMORY.exists() else ""
        if _already_present(memory_text, date):
            print(f"  [{date}] already in MEMORY.md, skipping")
            continue
        print(f"  [{date}] reflecting...", end=" ", flush=True)
        items = reflect_for_date(date)
        n = append_for_date(items, date)
        decisions = len(items.get("new_decisions") or [])
        lessons = len(items.get("new_lessons") or [])
        facts = len(items.get("new_facts") or [])
        print(f"-> {n} item(s) added (d:{decisions} l:{lessons} f:{facts})")
        total += n

    print(f"\nDone. {total} total item(s) added to MEMORY.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
