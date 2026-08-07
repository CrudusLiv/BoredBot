"""Deterministic scan of DEADLINES.md `## Active`.

Per HEARTBEAT.md: items get bucketed by urgency so the heartbeat can fire
threshold alerts (overdue / 24h / 72h) and rebuild the "Next 3" rollup.
Runs every tick before the LLM call, so deadline alerts don't depend on
Claude reasoning.

Buckets (relative to KL local today):
  overdue:     days < 0
  urgent:      0 <= days <= 1   (today / tomorrow)
  soon:        days == 2        (48h)
  approaching: days == 3        (72h)
  later:       days >= 4        (only relevant to the Next 3 rollup)
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
DEADLINES = PROJECT_DIR / "Dynamous" / "Memory" / "DEADLINES.md"
KL = timezone(timedelta(hours=8))

SECTION = "## Active"
# Matches: `- 2026-05-10 — CS101 — Assignment 1` and `- 2026-05-10 — title`.
# An optional `nogcal:` prefix (used to opt the row out of GCal sync) is
# tolerated so imminent alerts still fire for manually-scheduled items.
LINE_RE = re.compile(
    r"^-\s*(?:nogcal:\s*)?(\d{4}-\d{2}-\d{2})\s+—\s+(.+?)(?:\s+<!--.*-->)?\s*$",
    re.MULTILINE,
)

BUCKETS = ("overdue", "urgent", "soon", "approaching", "later")


def _section_text() -> str:
    if not DEADLINES.exists():
        return ""
    text = DEADLINES.read_text(encoding="utf-8")
    if SECTION not in text:
        return ""
    start = text.index(SECTION) + len(SECTION)
    next_section = text.find("\n## ", start)
    end = next_section if next_section != -1 else len(text)
    return text[start:end]


def _split_course_title(rest: str) -> tuple[str, str]:
    """Split `<course> — <title>` into (course, title). If no em-dash
    separator, the whole string is the title and course is empty."""
    if " — " in rest:
        course, _, title = rest.partition(" — ")
        return course.strip(), title.strip()
    return "", rest.strip()


def _key(due: str, course: str, title: str) -> str:
    """Stable per-row id for dashboard state idempotency. Changes if any of
    due/course/title change, which intentionally orphans the old thread and
    spawns a new one -- treat row edits as new deadlines."""
    return hashlib.sha1(f"{due}|{course}|{title}".encode("utf-8")).hexdigest()[:12]


def _bucket(days: int) -> str:
    if days < 0:
        return "overdue"
    if days <= 1:
        return "urgent"
    if days == 2:
        return "soon"
    if days == 3:
        return "approaching"
    return "later"


def scan(now: datetime | None = None) -> dict[str, list[dict]]:
    """Return all DEADLINES.md ## Active items grouped by urgency bucket.

    Each item dict carries: key, due, course, title, days, bucket.
    Order within a bucket follows source-file order."""
    now = now or datetime.now(KL)
    today = now.date()
    buckets: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for due_s, rest in LINE_RE.findall(_section_text()):
        try:
            due = date.fromisoformat(due_s)
        except ValueError:
            continue
        days = (due - today).days
        course, title = _split_course_title(rest)
        bucket = _bucket(days)
        buckets[bucket].append({
            "key": _key(due_s, course, title),
            "due": due_s,
            "course": course,
            "title": title,
            "days": days,
            "bucket": bucket,
        })
    return buckets


def actionable(buckets: dict[str, list[dict]]) -> list[dict]:
    """Items that warrant a forum-thread post (anything with a crossed
    threshold). Ordered overdue -> urgent -> soon -> approaching so the
    most urgent items create their threads first within a single tick."""
    out: list[dict] = []
    for b in ("overdue", "urgent", "soon", "approaching"):
        out.extend(buckets.get(b, []))
    return out


def all_upcoming(buckets: dict[str, list[dict]]) -> list[dict]:
    """Every item (including overdue + later), sorted by days ascending.
    Used to build the "Next 3 deadlines" rollup."""
    flat: list[dict] = []
    for b in BUCKETS:
        flat.extend(buckets.get(b, []))
    flat.sort(key=lambda i: i["days"])
    return flat
