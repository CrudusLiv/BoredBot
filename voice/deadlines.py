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
