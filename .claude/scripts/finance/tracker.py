"""Lightweight personal expense tracker.

Input format:
    <amount> <category> [note...]

Examples:
    50 food                       -> RM50, food
    12.50 transport bus to KLCC   -> RM12.50, transport, note "bus to KLCC"
    200 books semester textbooks  -> RM200, books, note "semester textbooks"

Output: one markdown table per month at `Dynamous/Memory/finance/YYYY-MM.md`,
with running totals appended on each write. The format is human-readable in
Obsidian and trivially parseable for future analytics.

This module is USER-SUPPLIED DATA ONLY. It never talks to a bank, never makes
purchases, never touches financial APIs. USER.md's hard-limit on "financial
data" is about external account access -- recording text the user explicitly
sends is just note-taking.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _finance_dir() -> Path:
    """Resolve the finance dir per call, reading CLAUDE_PROJECT_DIR each time so
    tests that monkeypatch the env var redirect writes to a temp vault."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return project_dir / "Dynamous" / "Memory" / "finance"

CURRENCY = "RM"  # Edit if you're not in MY. Single source of truth.
KL = timezone(timedelta(hours=8))

# Leading number, then a single word category, then optional free-text note.
# The category captures \w+ which excludes spaces -- "lunch with mom" cannot
# be a category, only a note. A leading connector word ("50 for travel pass")
# is skipped so the next real word becomes the category.
EXPENSE_RE = re.compile(
    r"^\s*(?P<amount>\d+(?:\.\d{1,2})?)\s+"
    r"(?:(?:for|on|at|to|of|in)\s+)?"
    r"(?P<category>[A-Za-z][\w-]*)\s*(?P<note>.*)$",
    re.IGNORECASE,
)


def parse(text: str) -> dict | None:
    """Return {amount: float, category: str, note: str} if the text looks
    like an expense entry, else None."""
    if not text:
        return None
    m = EXPENSE_RE.match(text.strip())
    if not m:
        return None
    try:
        amount = float(m.group("amount"))
    except ValueError:
        return None
    if amount <= 0:
        return None
    return {
        "amount": amount,
        "category": m.group("category").lower(),
        "note": (m.group("note") or "").strip(),
    }


def log(amount: float, category: str, note: str = "") -> dict:
    """Append one expense to the current month's file. Returns totals.

    Output dict: {
        "date": "YYYY-MM-DD HH:MM",
        "month_total": float,
        "category_total": float,
        "file": Path,
    }
    """
    now = datetime.now(KL)
    month_file = _month_file(now)
    if not month_file.exists():
        _init_month_file(month_file, now)

    # Shorter date in the table since the year is on the filename.
    timestamp = now.strftime("%m-%d %H:%M")
    # Escape pipes in note so the markdown table doesn't break.
    safe_note = (note or "").replace("|", "\\|")
    row = f"| {timestamp} | {CURRENCY} {amount:,.2f} | `{category}` | {safe_note} |"

    text = month_file.read_text(encoding="utf-8")
    text = _insert_row(text, row)
    text = _refresh_totals_block(text)
    text = _refresh_timeline_block(text, now)
    month_file.write_text(text, encoding="utf-8")

    _refresh_index()
    _refresh_neighbour_timelines(now)

    totals = _month_and_category_totals(month_file, category)
    return {
        "date": timestamp,
        "month_total": totals["month"],
        "category_total": totals["category"],
        "file": month_file,
    }


def month_summary(when: datetime | None = None) -> str:
    """Return a short human-readable summary for a given month (default: now)."""
    now = when or datetime.now(KL)
    month_file = _month_file(now)
    if not month_file.exists():
        return f"No expenses logged for {now.strftime('%B %Y')} yet."
    rows = _read_rows(month_file)
    if not rows:
        return f"No expenses logged for {now.strftime('%B %Y')} yet."
    total = sum(r["amount"] for r in rows)
    by_cat = defaultdict(float)
    for r in rows:
        by_cat[r["category"]] += r["amount"]
    lines = [f"{now.strftime('%B %Y')} -- {CURRENCY}{total:.2f} total"]
    for cat, amt in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {cat}: {CURRENCY}{amt:.2f}")
    return "\n".join(lines)


# ---------- File-level helpers ----------

ROW_RE = re.compile(
    # Date may be "YYYY-MM-DD HH:MM" (old format) or "MM-DD HH:MM" (new).
    # Currency may or may not have a space after (old vs new); amount may
    # have thousand separators. Category may be wrapped in backticks.
    r"^\|\s*(?P<ts>(?:\d{4}-)?\d{2}-\d{2} \d{2}:\d{2})\s*\|\s*"
    + re.escape(CURRENCY)
    + r"\s*(?P<amount>[\d,]+(?:\.\d+)?)\s*\|\s*`?(?P<category>[\w-]+)`?\s*\|\s*(?P<note>.*?)\s*\|\s*$"
)
# Section bounds use heading text directly -- no HTML comment markers
# cluttering the rendered note. Each helper finds its section by header,
# stops at the next ## or end-of-file, and rewrites or appends in place.
SUMMARY_H = "## Summary"
ENTRIES_H = "## Entries"
TIMELINE_H = "## Timeline"
NEXT_H_RE = re.compile(r"^## ", re.MULTILINE)
MONTH_RE = re.compile(r"^(\d{4}-\d{2})\.md$")


def _month_file(now: datetime) -> Path:
    d = _finance_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{now.strftime('%Y-%m')}.md"


def _init_month_file(path: Path, now: datetime) -> None:
    header = (
        f"---\n"
        f"type: finance\n"
        f"month: {now.strftime('%Y-%m')}\n"
        f"currency: {CURRENCY}\n"
        f"tags: [finance]\n"
        f"---\n\n"
        f"# Finance — {now.strftime('%B %Y')}\n\n"
        f"## Summary\n\n"
        f"_(no entries yet)_\n\n"
        f"## Entries\n\n"
        f"| Date | Amount | Category | Note |\n"
        f"|---|---:|---|---|\n\n"
        f"## Timeline\n\n"
        f"[[Finances|all months]]\n"
    )
    path.write_text(header, encoding="utf-8")


def _section_bounds(text: str, heading: str) -> tuple[int, int] | None:
    """Return (start, end) indices of a section's BODY (everything after the
    heading line, up to the next ## or EOF). Returns None if heading missing."""
    idx = text.find(heading)
    if idx == -1:
        return None
    nl = text.find("\n", idx)
    body_start = nl + 1 if nl != -1 else len(text)
    nxt = NEXT_H_RE.search(text, body_start)
    body_end = nxt.start() if nxt else len(text)
    return (body_start, body_end)


def _replace_section(text: str, heading: str, new_body: str) -> str:
    """Replace the body under `heading`. If the heading doesn't exist,
    append it at the end. Keeps one trailing blank line between sections."""
    new_body = new_body.rstrip() + "\n\n"
    bounds = _section_bounds(text, heading)
    if bounds is None:
        return text.rstrip() + f"\n\n{heading}\n\n{new_body}"
    start, end = bounds
    return text[:start].rstrip() + "\n\n" + new_body + text[end:]


def _insert_row(text: str, row: str) -> str:
    """Append a new row to the Entries table. The table sits in the Entries
    section; we find the last `|`-prefixed line in that section and insert
    after it."""
    bounds = _section_bounds(text, ENTRIES_H)
    if bounds is None:
        return text.rstrip() + "\n" + row + "\n"
    start, end = bounds
    section = text[start:end]
    # Find the last existing data row (skip the header and separator lines).
    lines = section.splitlines()
    last_row_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("|") and "---" not in line and "Date" not in line:
            last_row_idx = i
    if last_row_idx == -1:
        # No data rows yet -- append after the separator (the line with ---).
        for i, line in enumerate(lines):
            if "---" in line and line.startswith("|"):
                last_row_idx = i
                break
    if last_row_idx == -1:
        return text  # malformed table, bail
    lines.insert(last_row_idx + 1, row)
    new_section = "\n".join(lines).rstrip() + "\n\n"
    return text[:start] + new_section + text[end:]


def _refresh_totals_block(text: str) -> str:
    rows = _parse_rows_from_text(text)
    if not rows:
        body = "_(no entries yet)_"
    else:
        total = sum(r["amount"] for r in rows)
        by_cat: dict[str, float] = defaultdict(float)
        for r in rows:
            by_cat[r["category"]] += r["amount"]
        head = [
            f"> [!summary] {CURRENCY} {total:,.2f}",
            f"> {len(rows)} entries across {len(by_cat)} categor{'y' if len(by_cat) == 1 else 'ies'} this month.",
            "",
            "| Category | Amount | Share |",
            "|---|---:|---:|",
        ]
        for cat, amt in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            pct = (amt / total * 100) if total else 0.0
            head.append(f"| `{cat}` | {CURRENCY} {amt:,.2f} | {pct:.1f}% |")
        body = "\n".join(head)
    return _replace_section(text, SUMMARY_H, body)


def _refresh_timeline_block(text: str, now: datetime) -> str:
    prev_stem, next_stem = _neighbour_months(now)
    parts: list[str] = []
    if prev_stem:
        parts.append(f"← [[{prev_stem}]]")
    parts.append("[[Finances|all months]]")
    if next_stem:
        parts.append(f"[[{next_stem}]] →")
    body = " · ".join(parts)
    return _replace_section(text, TIMELINE_H, body)


def _neighbour_months(now: datetime) -> tuple[str | None, str | None]:
    """Return (prev_month_stem, next_month_stem) for files that exist on disk.
    Doesn't synthesise neighbours that don't have a file yet -- wikilinks to
    non-existent notes show as red placeholders, which is fine in Obsidian
    but a bit noisy. Only chain to real ones."""
    if not _finance_dir().exists():
        return (None, None)
    months = sorted(
        p.stem for p in _finance_dir().iterdir()
        if p.is_file() and MONTH_RE.match(p.name)
    )
    current = now.strftime("%Y-%m")
    if current not in months:
        return (None, None)
    i = months.index(current)
    prev_stem = months[i - 1] if i > 0 else None
    next_stem = months[i + 1] if i < len(months) - 1 else None
    return (prev_stem, next_stem)


def _refresh_neighbour_timelines(now: datetime) -> None:
    """When a new month file lands, the previous month's timeline needs to
    know about it. Same the other way for backfills."""
    prev_stem, next_stem = _neighbour_months(now)
    for stem in (prev_stem, next_stem):
        if not stem:
            continue
        path = _finance_dir() / f"{stem}.md"
        if not path.exists():
            continue
        # Parse the stem back to a datetime for the helper.
        try:
            stem_dt = datetime.strptime(stem, "%Y-%m").replace(tzinfo=KL)
        except ValueError:
            continue
        text = path.read_text(encoding="utf-8")
        new_text = _refresh_timeline_block(text, stem_dt)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")


def _refresh_index() -> None:
    """Maintain a hub note at finance/Finances.md listing every month with
    its total. The friendly filename ('Finances') shows up neatly in the
    Obsidian graph view instead of the generic 'index'."""
    if not _finance_dir().exists():
        return
    months = sorted(
        (p for p in _finance_dir().iterdir() if p.is_file() and MONTH_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,  # most recent first
    )
    if not months:
        return
    rows = ["| Month | Total | Top category |", "|---|---:|---|"]
    grand_total = 0.0
    for p in months:
        entries = _read_rows(p)
        total = sum(r["amount"] for r in entries)
        grand_total += total
        by_cat: dict[str, float] = defaultdict(float)
        for r in entries:
            by_cat[r["category"]] += r["amount"]
        if by_cat:
            top_cat, top_amt = max(by_cat.items(), key=lambda kv: kv[1])
            top = f"`{top_cat}` ({CURRENCY} {top_amt:,.2f})"
        else:
            top = "_(empty)_"
        # Pretty alias so the table reads "May 2026" instead of "2026-05".
        try:
            pretty = datetime.strptime(p.stem, "%Y-%m").strftime("%B %Y")
        except ValueError:
            pretty = p.stem
        rows.append(f"| [[{p.stem}|{pretty}]] | {CURRENCY} {total:,.2f} | {top} |")
    text = (
        "---\n"
        "type: finance-index\n"
        "tags: [finance]\n"
        "---\n\n"
        "# Finances — all months\n\n"
        f"> [!summary] Lifetime total\n> {CURRENCY} {grand_total:,.2f}\n\n"
        + "\n".join(rows)
        + "\n"
    )
    (_finance_dir() / "Finances.md").write_text(text, encoding="utf-8")
    # Remove the legacy index.md if it's still around from earlier writes.
    legacy = _finance_dir() / "index.md"
    if legacy.exists():
        legacy.unlink()


def _parse_rows_from_text(text: str) -> list[dict]:
    bounds = _section_bounds(text, ENTRIES_H)
    if bounds is None:
        return []
    start, end = bounds
    rows: list[dict] = []
    for line in text[start:end].splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        try:
            amount = float(m.group("amount").replace(",", ""))
        except ValueError:
            continue
        rows.append({
            "ts": m.group("ts"),
            "amount": amount,
            "category": m.group("category"),
            "note": m.group("note"),
        })
    return rows


def _read_rows(path: Path) -> list[dict]:
    return _parse_rows_from_text(path.read_text(encoding="utf-8"))


def _month_and_category_totals(path: Path, category: str) -> dict:
    rows = _read_rows(path)
    month = sum(r["amount"] for r in rows)
    cat = sum(r["amount"] for r in rows if r["category"] == category.lower())
    return {"month": month, "category": cat}
