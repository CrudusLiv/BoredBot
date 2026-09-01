"""Google Calendar push + delete.

Public API:
    create_event(title, date, description="", calendar_id="primary", *,
                 start_time=None, end_time=None, timezone="Asia/Kuala_Lumpur",
                 location=None, recur_until=None) -> event_id | None
    delete_event(title, date, calendar_id="primary") -> event_id | None
    parse_gcal_tags(text) -> list[(date, title)]
    parse_deadlines_md(text) -> list[(date, title)]

Dedup is by (title, date) on the same calendar, case-insensitive.
If a matching event already exists, create_event() returns None and does
NOT insert.

Deletion only happens on an explicit, confirmed, exact title+date match via
delete_event() — never as a side effect of the automated sync paths.
parse_gcal_tags()/parse_deadlines_md() still feed a strictly additive push;
they never delete. Manual edits in GCal outside of an explicit
delete_event() call are still preserved.
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
    *,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    timezone: str = "Asia/Kuala_Lumpur",
    location: Optional[str] = None,
    recur_until: Optional[str] = None,
) -> Optional[str]:
    """Create an event on `date` (YYYY-MM-DD) with `title`.

    Default is an all-day event. Pass `start_time`/`end_time` ("HH:MM", both
    required together) for a timed event in `timezone`. Pass `recur_until`
    (YYYY-MM-DD) to repeat weekly from `date` through that date inclusive.
    `location` sets the event location.

    Returns the event ID, or None if a duplicate (case-insensitive title +
    same start date) already exists on the calendar."""
    if start_time is not None and end_time is None:
        raise ValueError("end_time is required when start_time is given")

    service = _get_service()
    next_day = (date_cls.fromisoformat(date) + timedelta(days=1)).isoformat()

    # Dedup query: list events touching this date and check titles.
    existing = service.events().list(
        calendarId=calendar_id,
        timeMin=f"{date}T00:00:00Z",
        timeMax=f"{next_day}T00:00:00Z",
        singleEvents=True,
    ).execute()
    title_norm = title.strip().lower()
    for ev in existing.get("items") or []:
        ev_title = (ev.get("summary") or "").strip().lower()
        ev_start = (ev.get("start") or {}).get("date") or (ev.get("start") or {}).get("dateTime", "")[:10]
        if ev_title == title_norm and ev_start == date:
            return None

    if start_time is not None:
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": f"{date}T{start_time}:00", "timeZone": timezone},
            "end": {"dateTime": f"{date}T{end_time}:00", "timeZone": timezone},
        }
    else:
        body = {
            "summary": title,
            "description": description,
            "start": {"date": date},
            "end": {"date": next_day},
        }
    if location:
        body["location"] = location
    if recur_until:
        until = recur_until.replace("-", "")
        body["recurrence"] = [f"RRULE:FREQ=WEEKLY;UNTIL={until}T235959Z"]

    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created.get("id")


def delete_event(
    title: str,
    date: str,
    calendar_id: str = "primary",
) -> Optional[str]:
    """Delete the event titled `title` on `date` (YYYY-MM-DD).
    Returns the deleted event's ID, or None if no matching event was found.
    Raises ValueError if more than one event matches — never guesses which
    one to delete."""
    service = _get_service()
    end = (date_cls.fromisoformat(date) + timedelta(days=1)).isoformat()

    existing = service.events().list(
        calendarId=calendar_id,
        timeMin=f"{date}T00:00:00Z",
        timeMax=f"{end}T00:00:00Z",
        singleEvents=True,
    ).execute()
    title_norm = title.strip().lower()
    matches = []
    for ev in existing.get("items") or []:
        ev_title = (ev.get("summary") or "").strip().lower()
        ev_start = (ev.get("start") or {}).get("date") or (ev.get("start") or {}).get("dateTime", "")[:10]
        if ev_title == title_norm and ev_start == date:
            matches.append(ev)

    if not matches:
        return None
    if len(matches) > 1:
        titles = ", ".join(repr(m.get("summary", "")) for m in matches)
        raise ValueError(f"{len(matches)} events match {title!r} on {date}: {titles}")

    event_id = matches[0]["id"]
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return event_id


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
