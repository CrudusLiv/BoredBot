#!/usr/bin/env python3
"""Daily reflection -- runs at 08:00 UTC+8.

Two jobs each morning:
1. Read yesterday's daily/<YYYY-MM-DD>.md, ask Claude for durable items
   (decisions, lessons, facts), append them to MEMORY.md under the matching
   sections. Ruthlessly small lists -- most days produce 0-2 items.
2. Archive yesterday's HABITS.md to goals/habits-history/, reset today's
   checkboxes for a fresh day."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])

sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
from core import llm  # noqa: E402

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
DAILY = VAULT / "daily"
HABITS = VAULT / "HABITS.md"
HABITS_HISTORY = VAULT / "goals" / "habits-history"
MEMORY = VAULT / "MEMORY.md"

KL = timezone(timedelta(hours=8))

REFLECT_SYSTEM = """You curate CrudusLiv's long-term memory.

You receive yesterday's daily log and the current MEMORY.md. Output STRICT
JSON only -- no prose, no markdown fences:

{
  "new_decisions": ["one line each -- durable choices made yesterday"],
  "new_lessons":   ["one line each -- what worked, what didn't, what to do differently"],
  "new_facts":     ["one line each -- non-obvious facts about systems/people/projects"]
}

Rules:
- Be RUTHLESS. Most chatter is not durable. Empty arrays are correct most days.
- Don't duplicate items already present in MEMORY.md.
- Each item <= 100 chars. No headers, no markdown formatting in items.
- Skip small fixes, debugging steps, and in-the-moment decisions that won't matter
  next month."""


def yesterday_kl() -> str:
    return (datetime.now(KL) - timedelta(days=1)).strftime("%Y-%m-%d")


def today_kl() -> str:
    return datetime.now(KL).strftime("%Y-%m-%d")


# ---------- Reflection ----------

def reflect() -> dict:
    y_path = DAILY / f"{yesterday_kl()}.md"
    if not y_path.exists():
        print(f"No daily log at {y_path}. Skipping reflection.")
        return {}
    y_log = y_path.read_text(encoding="utf-8")
    memory = MEMORY.read_text(encoding="utf-8") if MEMORY.exists() else ""

    if not llm.is_available():
        print("`claude` CLI not available. Reflection skipped.", file=sys.stderr)
        return {}

    prompt = (
        f"YESTERDAY'S DAILY LOG ({y_path.name}):\n\n{y_log}\n\n"
        f"---\n\nCURRENT MEMORY.md:\n\n{memory}\n\n"
        f"Return JSON per the schema."
    )
    return llm.call_json(prompt, system_prompt=REFLECT_SYSTEM, model="haiku", task="memory_reflect") or {}


def _insert_into_section(text: str, section_name: str, new_items: list[str], date_prefix: str) -> tuple[str, int]:
    """Append new bullets at the END of `## section_name` (before the next ## block)."""
    marker = f"## {section_name}"
    if marker not in text or not new_items:
        return text, 0
    start = text.index(marker)
    next_section = text.find("\n## ", start + 1)
    end = next_section if next_section != -1 else len(text)
    section = text[start:end].rstrip()
    additions = "".join(f"- {date_prefix} — {item.strip()}\n" for item in new_items)
    new_section = section + "\n" + additions
    return text[:start] + new_section + ("\n" + text[end:].lstrip("\n") if next_section != -1 else ""), len(new_items)


def append_to_memory(items: dict) -> int:
    if not items or not MEMORY.exists():
        return 0
    text = MEMORY.read_text(encoding="utf-8")
    today = today_kl()
    appended = 0
    for section, key in (("Decisions", "new_decisions"), ("Lessons", "new_lessons")):
        new = items.get(key) or []
        text, n = _insert_into_section(text, section, new, today)
        appended += n
    facts = items.get("new_facts") or []
    if facts:
        text, n = _insert_into_section(text, "Lessons", [f"(fact) {f}" for f in facts], today)
        appended += n
    if appended:
        MEMORY.write_text(text, encoding="utf-8")
    return appended


# ---------- Habits reset ----------

def _add_archive_nav(archive: Path, prev_date: str | None) -> None:
    """Append a prev-link + back-to-HABITS nav footer to a habits archive file."""
    text = archive.read_text(encoding="utf-8")
    if "[[HABITS|all days]]" in text:
        return
    if prev_date:
        footer = f"\n← [[goals/habits-history/{prev_date}|{prev_date}]] · [[HABITS|all days]]\n"
    else:
        footer = "\n[[HABITS|all days]]\n"
    archive.write_text(text.rstrip() + "\n" + footer, encoding="utf-8")


def _prepend_history_link(date: str) -> None:
    """Prepend a wikilink for `date` into the ## History section of HABITS.md."""
    if not HABITS.exists():
        return
    text = HABITS.read_text(encoding="utf-8")
    marker = "_(Filled by the heartbeat. Newest at top.)_"
    if marker not in text:
        return
    link = f"- [[goals/habits-history/{date}|{date}]]"
    text = text.replace("\n- _(empty — no history yet)_", "")
    text = text.replace(marker, marker + "\n" + link)
    HABITS.write_text(text, encoding="utf-8")


def reset_habits() -> str:
    if not HABITS.exists():
        return "no HABITS.md"
    HABITS_HISTORY.mkdir(parents=True, exist_ok=True)
    yesterday = yesterday_kl()
    today = today_kl()

    text = HABITS.read_text(encoding="utf-8")

    archive = HABITS_HISTORY / f"{yesterday}.md"
    if not archive.exists():
        archive.write_text(text, encoding="utf-8")
        all_archives = sorted(p.stem for p in HABITS_HISTORY.glob("*.md") if p.stem != yesterday)
        prev_date = all_archives[-1] if all_archives else None
        _add_archive_nav(archive, prev_date)
        _prepend_history_link(yesterday)

    text = re.sub(
        r"## Today — \d{4}-\d{2}-\d{2}",
        f"## Today — {today}",
        text,
    )
    today_marker = f"## Today — {today}"
    start = text.find(today_marker)
    if start != -1:
        next_section = text.find("\n## ", start + 1)
        end = next_section if next_section != -1 else len(text)
        before, section, after = text[:start], text[start:end], text[end:]
        section = section.replace("- [x]", "- [ ]").replace("- [X]", "- [ ]")
        text = before + section + after
        HABITS.write_text(text, encoding="utf-8")
        return f"reset (archived {yesterday})"
    return "no Today section"


ABOUT_SYSTEM = """You curate ABOUT.md — durable facts about CrudusLiv himself
(preferences, working style, recurring patterns), not project state.

You receive yesterday's chat-session messages (in #vesper) and the current
ABOUT.md. Output STRICT JSON only:

{"new_bullets": ["one line each, <= 100 chars, no markdown"]}

Rules:
- Be RUTHLESS. Most exchanges produce nothing. Empty arrays are correct most days.
- Only include facts that will still be true next month.
- Skip task-specific or project-specific items — those belong in MEMORY.md.
- Don't duplicate existing ABOUT.md bullets."""


def _yesterday_chat_messages() -> str:
    """Return yesterday's chat messages as a single string, or '' if none."""
    import sqlite3
    from datetime import datetime as _dt, timedelta as _td
    db = PROJECT_DIR / ".claude" / "data" / "chat.db"
    if not db.exists():
        return ""
    y_start = _dt.combine((_dt.now(KL) - _td(days=1)).date(), _dt.min.time(), tzinfo=KL).timestamp()
    y_end = y_start + 86400
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE ts >= ? AND ts < ? ORDER BY ts",
            (y_start, y_end),
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return ""
    return "\n".join(f"{role.upper()}: {content}" for role, content in rows)


def curate_about() -> int:
    """Returns the number of new bullets added (0 on no-op)."""
    sys.path.insert(0, str(PROJECT_DIR / ".claude"))
    from chat import about

    chat_msgs = _yesterday_chat_messages()
    if not chat_msgs.strip():
        print("No chat messages yesterday. Skipping ABOUT curation.")
        return 0
    if not llm.is_available():
        print("`claude` CLI not available. ABOUT curation skipped.", file=sys.stderr)
        return 0

    current = about.load_about()
    prompt = (
        f"YESTERDAY'S #VESPER CHAT MESSAGES:\n\n{chat_msgs}\n\n"
        f"---\n\nCURRENT ABOUT.md:\n\n{current}\n\n"
        f"Return JSON per the schema."
    )
    result = llm.call_json(prompt, system_prompt=ABOUT_SYSTEM, model="haiku", task="memory_about") or {}
    new_bullets = result.get("new_bullets") or []
    if not isinstance(new_bullets, list):
        return 0

    added = 0
    for bullet in new_bullets[:3]:
        if isinstance(bullet, str) and about.append_bullet(bullet):
            added += 1
    print(f"ABOUT curation: added {added} bullet(s).")
    return added


def _post_morning_digest() -> None:
    try:
        import schedule_parser
        from core import habits, dashboard
    except ImportError as exc:
        print(f"morning digest skipped (import error): {exc}", file=sys.stderr)
        return

    view = schedule_parser.schedule_view()
    today_abbr = datetime.now(KL).strftime("%a")
    classes = [e for e in (view or {}).get("entries", []) if e.get("day") == today_abbr]

    lines: list[str] = []
    if classes:
        lines.append("**Classes today**")
        for cls in classes:
            loc = f" · {cls['location']}" if cls.get("location") else ""
            lines.append(f"  └─ {cls['course']} · {cls['type']}  {cls['start']}–{cls['end']}{loc}")
        lines.append("")

    pillar_names = habits.get_pillar_names()
    if pillar_names:
        lines.append("**Habits**")
        for p in pillar_names:
            lines.append(f"  □ {p}")

    body = "\n".join(lines) if lines else "New day. Checkboxes reset."
    try:
        dashboard.notify("morning_digest", {"body": body})
    except Exception as exc:
        print(f"morning digest post failed (non-fatal): {exc}", file=sys.stderr)


def main() -> int:
    items = reflect()
    appended = append_to_memory(items)
    habits_status = reset_habits()
    print(f"Reflection: {appended} item(s) added to MEMORY.md.")
    print(f"Habits: {habits_status}.")
    _post_morning_digest()
    try:
        curate_about()
    except Exception as exc:
        print(f"ABOUT curation failed (non-fatal): {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
