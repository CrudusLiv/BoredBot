"""GCal → DEADLINES.md import, and mark-complete.

The vault→GCal push (gcal_write) is strictly additive toward Google Calendar;
this module closes the loop in the other direction: calendar events whose
titles look like deadlines become `- nogcal: YYYY-MM-DD — title` rows under
`## Active` (nogcal: so the push never re-creates the event). Completing a
deadline moves its row to `## Done` with a date stamp — `core/imminent.py`
only scans `## Active`, so alerts stop immediately and history is kept.
"""
from __future__ import annotations

import re
from typing import Iterable

DEFAULT_KEYWORDS = [
    "due", "deadline", "submission", "submit", "payment", "bill",
    "renewal", "expires", "application", "interview", "appointment",
]

# `- [nogcal:] YYYY-MM-DD — rest [✓ done YYYY-MM-DD]`
_ROW_RE = re.compile(
    r"^-\s*(?:nogcal:\s*)?(\d{4}-\d{2}-\d{2})\s+—\s+(.+?)(?:\s+✓ done \d{4}-\d{2}-\d{2})?\s*$"
)


def _norm(title: str) -> str:
    # Punctuation-insensitive: a vault row "MPU — Reflection submission" must
    # dedupe against the calendar event "MPU Reflection submission".
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title.lower())).strip()


def filter_deadline_events(events: Iterable[dict], keywords: list[str]) -> list[tuple[str, str]]:
    """(date, title) for events whose title contains a deadline keyword
    (word-boundary, case-insensitive). `start` may be a date or datetime."""
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE
    )
    out: list[tuple[str, str]] = []
    for ev in events:
        title = (ev.get("summary") or "").strip()
        date = str(ev.get("start") or "")[:10]
        if title and re.match(r"\d{4}-\d{2}-\d{2}$", date) and pattern.search(title):
            out.append((date, title))
    return out


def _existing_keys(md_text: str) -> set[tuple[str, str]]:
    keys = set()
    for line in md_text.splitlines():
        m = _ROW_RE.match(line.strip())
        if m:
            keys.add((m.group(1), _norm(m.group(2))))
    return keys


def _insert_into_section(text: str, heading: str, rows: list[str]) -> str:
    """Append rows at the end of `heading`'s section, creating it at EOF if absent."""
    idx = text.find(heading)
    if idx == -1:
        return text.rstrip("\n") + f"\n\n{heading}\n\n" + "\n".join(rows) + "\n"
    nxt = text.find("\n## ", idx + len(heading))
    head, tail = (text, "") if nxt == -1 else (text[:nxt], text[nxt:])
    return head.rstrip("\n") + "\n" + "\n".join(rows) + "\n" + tail


def merge_events(md_text: str, pairs: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Add unseen (date, title) pairs to ## Active as nogcal rows.
    Returns (new_text, added) where added is ["date — title", ...]."""
    existing = _existing_keys(md_text)
    new_rows, added = [], []
    for date, title in pairs:
        key = (date, _norm(title))
        if key in existing:
            continue
        existing.add(key)
        new_rows.append(f"- nogcal: {date} — {title}")
        added.append(f"{date} — {title}")
    if not new_rows:
        return md_text, []
    return _insert_into_section(md_text, "## Active", new_rows), added


def prune_deleted(md_text: str, events: Iterable[dict], keywords: list[str] | None,
                   window_start: str, window_end: str) -> tuple[str, list[str]]:
    """Remove nogcal ## Active rows dated inside [window_start, window_end]
    (the calendar fetch window) that no longer match any event in `events` --
    the source event was deleted straight from Google Calendar, so without
    this the row would keep firing threshold alerts forever with no way to
    clear it. Plain (non-nogcal) rows are left alone; they were never sourced
    from a calendar import. Returns (new_text, removed)."""
    current = {(date, _norm(title)) for date, title in filter_deadline_events(events, keywords or DEFAULT_KEYWORDS)}
    lo, hi = _active_bounds(md_text)
    section = md_text[lo:hi]
    removed: list[str] = []
    kept_lines: list[str] = []
    for line in section.split("\n"):
        row = line.strip()
        m = _ROW_RE.match(row)
        if m and row.startswith("- nogcal:"):
            date, title = m.group(1), m.group(2)
            if window_start <= date <= window_end and (date, _norm(title)) not in current:
                removed.append(f"{date} — {title}")
                continue
        kept_lines.append(line)
    if not removed:
        return md_text, []
    return md_text[:lo] + "\n".join(kept_lines) + md_text[hi:], removed


def _active_bounds(text: str) -> tuple[int, int]:
    idx = text.find("## Active")
    if idx == -1:
        return (0, 0)
    start = idx + len("## Active")
    nxt = text.find("\n## ", start)
    return (start, len(text) if nxt == -1 else nxt)


def complete(md_text: str, query: str, today: str) -> tuple[str, str | None]:
    """Move the first ## Active row whose text matches `query`
    (case-insensitive substring) to ## Done with a `✓ done <today>` stamp.
    Returns (new_text, moved_row) or (md_text, None) if nothing matched."""
    lo, hi = _active_bounds(md_text)
    q = _norm(query)
    for line in md_text[lo:hi].splitlines():
        row = line.strip()
        if _ROW_RE.match(row) and q in _norm(row):
            without = md_text[:lo] + md_text[lo:hi].replace(line + "\n", "", 1) + md_text[hi:]
            stamped = f"{row} ✓ done {today}"
            return _insert_into_section(without, "## Done", [stamped]), row
    return md_text, None


# ── vault IO ──────────────────────────────────────────────────────────────────

def _path():
    from voice import config as cfg
    vault = cfg.get_vault_dir()
    return None if vault is None else vault / "DEADLINES.md"


def import_from_events(events: Iterable[dict], keywords: list[str] | None = None) -> list[str]:
    """Filter + merge into the vault's DEADLINES.md. Returns rows added."""
    p = _path()
    if p is None or not p.exists():
        return []
    pairs = filter_deadline_events(events, keywords or DEFAULT_KEYWORDS)
    if not pairs:
        return []
    text = p.read_text(encoding="utf-8")
    new_text, added = merge_events(text, pairs)
    if added:
        p.write_text(new_text, encoding="utf-8")
    return added


def add_rows(pairs: list[tuple[str, str]]) -> list[str]:
    """Merge (iso_date, title) pairs into DEADLINES.md ## Active as nogcal
    rows. Like import_from_events but for non-calendar sources (e.g. the
    university intake). Returns rows added ("date — title")."""
    p = _path()
    if p is None or not p.exists() or not pairs:
        return []
    text = p.read_text(encoding="utf-8")
    new_text, added = merge_events(text, pairs)
    if added:
        p.write_text(new_text, encoding="utf-8")
    return added


def sync_with_calendar(events: Iterable[dict], keywords: list[str] | None = None,
                        days_back: int = 0, days_forward: int = 30) -> tuple[list[str], list[str]]:
    """Two-way sync against a calendar fetch window covering
    [today - days_back, today + days_forward]: adds newly-seen deadline
    events (see import_from_events), then prunes nogcal rows dated inside
    that same window whose source event is gone from `events` -- covers
    deletions made directly in Google Calendar, which never touch
    DEADLINES.md on their own. Returns (added, removed)."""
    p = _path()
    if p is None or not p.exists():
        return [], []
    events = list(events)
    from datetime import datetime, timedelta
    from voice import config as cfg
    today = datetime.now(cfg.get_timezone()).date()
    window_start = (today - timedelta(days=days_back)).isoformat()
    window_end = (today + timedelta(days=days_forward)).isoformat()

    text = p.read_text(encoding="utf-8")
    pairs = filter_deadline_events(events, keywords or DEFAULT_KEYWORDS)
    text, added = merge_events(text, pairs)
    text, removed = prune_deleted(text, events, keywords, window_start, window_end)
    if added or removed:
        p.write_text(text, encoding="utf-8")
    return added, removed


def complete_deadline(query: str) -> str:
    """Voice tool: mark a deadline done by a few words from its title."""
    from datetime import datetime
    from voice import config as cfg
    p = _path()
    if p is None or not p.exists():
        return "No DEADLINES.md in the vault."
    today = datetime.now(cfg.get_timezone()).date().isoformat()
    text = p.read_text(encoding="utf-8")
    new_text, row = complete(text, query, today)
    if row is None:
        return f"No active deadline matches {query!r}."
    p.write_text(new_text, encoding="utf-8")
    return f"Done: {row.lstrip('- ')} — moved to Done."
