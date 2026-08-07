"""Section 6: one-way Google Calendar push.

Public API:
    create_event(title, date, description="", calendar_id="primary") -> event_id | None
    parse_gcal_tags(text) -> list[(date, title)]
    parse_deadlines_md(text) -> list[(date, title)]

Dedup is by (title, date) on the same calendar, case-insensitive.
If a matching event already exists, returns None and does NOT insert.

This module never deletes or updates events. Manual edits in GCal are
preserved; the side-effect surface is strictly additive.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date as date_cls, timedelta
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])


def _get_service():
    """Return an authorised Google Calendar v3 client. Lazy import so tests
    can monkey-patch this without pulling in google-api-python-client."""
    sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts" / "integrations"))
    from google_auth import get_credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(
    title: str,
    date: str,
    description: str = "",
    calendar_id: str = "primary",
) -> Optional[str]:
    """Create an all-day event on `date` (YYYY-MM-DD) with `title`.
    Returns the event ID, or None if a duplicate (case-insensitive title +
    same date) already exists on the calendar."""
    service = _get_service()
    start = date
    end = (date_cls.fromisoformat(date) + timedelta(days=1)).isoformat()

    # Dedup query: list events touching this date and check titles.
    existing = service.events().list(
        calendarId=calendar_id,
        timeMin=f"{date}T00:00:00Z",
        timeMax=f"{end}T00:00:00Z",
        singleEvents=True,
    ).execute()
    title_norm = title.strip().lower()
    for ev in existing.get("items") or []:
        ev_title = (ev.get("summary") or "").strip().lower()
        ev_start = (ev.get("start") or {}).get("date") or (ev.get("start") or {}).get("dateTime", "")[:10]
        if ev_title == title_norm and ev_start == date:
            return None

    body = {
        "summary": title,
        "description": description,
        "start": {"date": start},
        "end": {"date": end},
    }
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created.get("id")


def parse_gcal_tags(text: str) -> list[tuple[str, str]]:
    """Find `gcal: <YYYY-MM-DD> | <title>` lines. Skip lines that already
    carry a [synced:<id>] suffix."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if "[synced:" in line:
            continue
        m = re.search(r"gcal:\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+)$", line)
        if not m:
            continue
        out.append((m.group(1), m.group(2).strip()))
    return out


_DEADLINE_ROW_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s+—\s+(.+)$")


def parse_deadlines_md(text: str) -> list[tuple[str, str]]:
    """Parse DEADLINES.md rows. Format: `- YYYY-MM-DD — <title>`. Skip rows
    prefixed with `nogcal:`."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        if "nogcal:" in raw:
            continue
        m = _DEADLINE_ROW_RE.match(raw.strip()) if raw.strip().startswith("-") else None
        # Allow either an em-dash or a hyphen sequence after the date.
        if not m:
            m = re.match(r"^-\s+(\d{4}-\d{2}-\d{2})\s*[—-]+\s*(.+)$", raw.strip())
        if not m:
            continue
        out.append((m.group(1), m.group(2).strip()))
    return out
