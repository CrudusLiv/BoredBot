"""Parse timetable text via LLM into structured schedule entries."""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from core import llm

_PARSE_PROMPT = """\
Extract EVERY class/lecture/tutorial entry from this timetable as JSON.
Return ONLY a JSON array, no other text:
[{{"course": "CS101", "days": ["Mon","Wed","Fri"], "start": "08:00", "end": "09:30", "type": "lecture", "location": "Room A1"}}, ...]

Rules:
- Extract every entry. Do NOT skip, drop, summarise, or invent entries.
- Emit one object per (course, day, start time). Only combine multiple days into
  one object when the SAME course runs at the SAME start AND end time AND the
  SAME location on each.
- Days must use 3-letter abbreviations: Mon Tue Wed Thu Fri Sat Sun.
- Times must be HH:MM (24-hour); convert am/pm (e.g. 2pm -> 14:00, 2:30pm -> 14:30).
- "type" is the parenthesised kind, lowercased (e.g. lecture, tutorial); default "class".
- "location" is the room/venue (e.g. EMPH, BLH2.2, ALH2.6, Online); use "" if none.
- Include every entry from the input — do not omit any. Output the JSON array only.

Timetable:
{text}"""

_ABBR_TO_FULL = {
    "Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday",
    "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday",
}


def _proj() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def _vault() -> Path:
    return _proj() / "Dynamous" / "Memory"


def _data_dir() -> Path:
    return _proj() / ".claude" / "data"


def _pending_path() -> Path:
    return _data_dir() / "schedule_pending.json"


def parse_timetable(text: str) -> tuple[list[dict], str]:
    """Parse raw timetable text via LLM. Returns (entries, human_summary).
    Raises ValueError if LLM returns empty or malformed JSON."""
    # Sonnet, not haiku: haiku silently drops entries from dense, run-on
    # timetable strings (observed dropping 4 of 8). Schedule parsing is rare
    # (once a semester), so the extra latency/cost is worth the reliability.
    entries = llm.call_json(_PARSE_PROMPT.format(text=text), model="sonnet")
    if not isinstance(entries, list) or not entries:
        raise ValueError("empty or malformed JSON from LLM")
    parts: list[str] = []
    try:
        for e in entries:
            days_str = "/".join(e.get("days", []))
            loc = e.get("location", "")
            suffix = f" @ {loc}" if loc else ""
            parts.append(f"{e['course']} {days_str} {e['start']}–{e['end']}{suffix}")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"empty or malformed JSON from LLM: {exc}") from exc
    return entries, ", ".join(parts)


def _parse_time(t: str) -> int:
    """HH:MM → minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


# Course colour coding. Emoji squares render identically on Obsidian desktop,
# mobile, and export, and pass through to Discord. Assigned by order of first
# appearance so any future course gets a colour automatically.
_PALETTE = ["🟦", "🟩", "🟧", "🟪", "🟥", "🟨", "🟫", "⬛"]
_PALETTE_COLOR: dict[str, int] = {
    "🟦": 0x89b4fa, "🟩": 0xa6e3a1, "🟧": 0xfab387, "🟪": 0xcba6f7,
    "🟥": 0xf38ba8, "🟨": 0xf9e2af, "🟫": 0x9a6b4b, "⬛": 0x6c7086,
}
_SCHEDULE_FALLBACK_COLOR = 0x8A7FB5


def _course_colors(entries: list[dict]) -> dict[str, str]:
    """Map each course code to a palette emoji, by order of first appearance."""
    colors: dict[str, str] = {}
    for e in entries:
        course = e.get("course")
        if course and course not in colors:
            colors[course] = _PALETTE[len(colors) % len(_PALETTE)]
    return colors


def write_schedule(entries: list[dict]) -> None:
    """Write or overwrite SCHEDULE.md as a flat markdown table.
    One row per (course, day) occurrence, sorted by weekday then start time.
    Preserves existing semester: frontmatter on overwrite; uses TBD on fresh write."""
    schedule_path = _vault() / "SCHEDULE.md"

    semester = "TBD"
    if schedule_path.exists():
        existing = schedule_path.read_text(encoding="utf-8")
        m = re.search(r"^semester:\s*(.+)$", existing, re.MULTILINE)
        if m:
            semester = m.group(1).strip()

    today = date.today().isoformat()

    # Expand multi-day entries: one row per (course, day) occurrence
    rows: list[dict] = []
    for e in entries:
        for abbr in e.get("days", []):
            rows.append({
                "course": e.get("course", ""),
                "type": e.get("type", "class"),
                "day": abbr,
                "start": e.get("start", ""),
                "end": e.get("end", ""),
                "location": e.get("location", ""),
            })

    _day_order = {d: i for i, d in enumerate(_ABBR_TO_FULL)}
    rows.sort(key=lambda r: (_day_order.get(r["day"], 99), _parse_time(r["start"])))

    table = [
        "| Course | Type | Day | Start | End | Room |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        table.append(
            f"| {r['course']} | {r['type']} | {r['day']} | {r['start']} | {r['end']} | {r['location']} |"
        )

    content = f"---\nsemester: {semester}\nupdated: {today}\n---\n\n" + "\n".join(table) + "\n"
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_text(content, encoding="utf-8")


def has_existing_schedule() -> bool:
    """True iff SCHEDULE.md contains the flat-table header row."""
    path = _vault() / "SCHEDULE.md"
    if not path.exists():
        return False
    return "| Course |" in path.read_text(encoding="utf-8")


def schedule_view() -> dict | None:
    """Parse the active SCHEDULE.md flat table. Returns None when missing or
    has no table header. Shape:
        {"semester": str, "updated": str,
         "entries": [{"course", "type", "day", "start", "end", "location"}, ...]}
    Entries are in the same order as the table rows (day then start time)."""
    path = _vault() / "SCHEDULE.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if "| Course |" not in text:
        return None

    sm = re.search(r"^semester:\s*(.+)$", text, re.MULTILINE)
    um = re.search(r"^updated:\s*(.+)$", text, re.MULTILINE)

    entries: list[dict] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| Course |"):
                in_table = True
            continue
        if re.fullmatch(r"[\|\-\s:]+", stripped):  # separator row (| --- | --- |)
            continue
        if not stripped.startswith("|"):
            break
        cols = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cols) >= 6:
            entries.append({
                "course": cols[0],
                "type": cols[1],
                "day": cols[2],
                "start": cols[3],
                "end": cols[4],
                "location": cols[5],
            })

    return {
        "semester": sm.group(1).strip() if sm else "",
        "updated": um.group(1).strip() if um else "",
        "entries": entries,
    }


def schedule_embeds(data: dict) -> list[dict]:
    """Group schedule_view() data into per-day embed dicts for Discord.

    Returns list of dicts — one per active weekday in Mon→Sun order:
        {"title": str, "color": int, "lines": [str, ...], "footer": str | None}
    Color is derived from the first course's palette slot for that day.
    Footer (semester · updated) appears only on the last embed.
    """
    entries = data.get("entries", [])
    if not entries:
        return []

    colors = _course_colors(entries)

    # Group by day; _ABBR_TO_FULL insertion order gives Mon→Sun
    day_map: dict[str, list[dict]] = {}
    for e in entries:
        day_map.setdefault(e["day"], []).append(e)
    active_days = [abbr for abbr in _ABBR_TO_FULL if abbr in day_map]

    result: list[dict] = []
    for i, abbr in enumerate(active_days):
        classes = day_map[abbr]
        first_emoji = colors.get(classes[0]["course"], "")
        color = _PALETTE_COLOR.get(first_emoji, _SCHEDULE_FALLBACK_COLOR)

        lines = []
        for e in classes:
            emoji = colors.get(e["course"], "")
            loc = f" · {e['location']}" if e.get("location") else ""
            lines.append(f"{emoji} **{e['start']}–{e['end']}** {e['course']} · {e['type']}{loc}")

        footer: str | None = None
        if i == len(active_days) - 1:
            bits = [b for b in (
                data.get("semester", ""),
                f"updated {data['updated']}" if data.get("updated") else "",
            ) if b]
            footer = " · ".join(bits) if bits else None

        result.append({
            "title": _ABBR_TO_FULL[abbr],
            "color": color,
            "lines": lines,
            "footer": footer,
        })

    return result


def read_pending() -> list[dict] | None:
    """Return pending entries from schedule_pending.json, or None if missing/malformed."""
    try:
        data = json.loads(_pending_path().read_text(encoding="utf-8"))
        return data.get("entries")
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return None


def write_pending(entries: list[dict]) -> None:
    """Persist parsed entries to schedule_pending.json to await confirmation."""
    path = _pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "parsed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_pending() -> None:
    """Delete schedule_pending.json (no-ops silently if already gone)."""
    try:
        _pending_path().unlink()
    except FileNotFoundError:
        pass
