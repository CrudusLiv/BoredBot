"""Google Calendar Reminders -- backed by the Google Tasks API (Calendar's
own "Reminders" toggle is a Tasks-API view, not a Calendar-API resource).

Public API:
    create_reminder(title, date, description="", tasklist="@default") -> task_id | None
    list_reminders(days=7, tasklist="@default") -> [{"id","title","due","notes"}, ...]
    due_reminders(tasklist="@default") -> [{"id","title","due","notes"}, ...]
    complete_reminder(title, tasklist="@default") -> task_id | None

Dedup is by (title, date) on the given task list, case-insensitive. If a
matching reminder already exists, create_reminder() returns None and does
NOT insert.

No delete function -- only creation, listing, and completion are supported
here.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])


def _get_service(interactive: bool = True):
    """Return an authorised Google Tasks v1 client, or None when no
    credentials are available and interactive=False (a background caller
    that must not block on a consent prompt). Lazy import so tests can
    monkey-patch this without pulling in google-api-python-client."""
    sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts" / "integrations"))
    from google_auth import get_credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    creds = get_credentials(interactive=interactive)
    if not creds:
        return None
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def create_reminder(
    title: str,
    date: str,
    description: str = "",
    tasklist: str = "@default",
) -> Optional[str]:
    """Create a reminder (Google Task) titled `title`, due `date`
    (YYYY-MM-DD). Returns the task ID, or None if a duplicate (same title,
    same due date) already exists on `tasklist`."""
    service = _get_service()
    due = f"{date}T00:00:00.000Z"

    existing = service.tasks().list(tasklist=tasklist, showCompleted=False).execute()
    title_norm = title.strip().lower()
    for t in existing.get("items") or []:
        t_title = (t.get("title") or "").strip().lower()
        t_due = (t.get("due") or "")[:10]
        if t_title == title_norm and t_due == date:
            return None

    body = {"title": title, "notes": description, "due": due}
    created = service.tasks().insert(tasklist=tasklist, body=body).execute()
    return created.get("id")


def list_reminders(days: int = 7, tasklist: str = "@default",
                   interactive: bool = True) -> list[dict]:
    """List uncompleted reminders due within the next `days` days on
    `tasklist`, sorted by due date. Returns
    [{"id", "title", "due", "notes"}, ...].

    dueMin floors to the start of today (UTC) rather than the exact instant
    of the call. Every due date is written as T00:00:00.000Z (see
    create_reminder above) regardless of the caller's local day, so once
    real UTC time ticks past midnight -- true for almost all of a UTC+8
    day -- a same-day reminder's due timestamp is technically already in
    the past, and the Tasks API's dueMin filter would silently drop it for
    the rest of the day."""
    service = _get_service(interactive=interactive)
    if service is None:
        return []
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    later = start_of_day + timedelta(days=days)
    resp = service.tasks().list(
        tasklist=tasklist,
        showCompleted=False,
        dueMin=start_of_day.isoformat(),
        dueMax=later.isoformat(),
    ).execute()
    out = [
        {
            "id": t.get("id"),
            "title": t.get("title", ""),
            "due": t.get("due"),
            "notes": t.get("notes", ""),
        }
        for t in resp.get("items") or []
    ]
    out.sort(key=lambda r: r.get("due") or "")
    return out


def due_reminders(tasklist: str = "@default", interactive: bool = True) -> list[dict]:
    """List uncompleted reminders already at or past their due date --
    unlike list_reminders()'s rolling upcoming-days window, this has no
    lower bound, so overdue reminders (however old) are always included.
    Backs the heartbeat's repeat-until-done voice nag (see
    voice/heartbeat.py _check_reminder_nags). Sorted by due date.

    dueMax is bumped to the start of tomorrow (UTC) rather than the exact
    instant of the call. The Tasks API's dueMax filter compares by whole
    calendar day, so a same-day reminder (always stored as T00:00:00.000Z,
    see create_reminder above) is excluded for the entire day it's due --
    dueMax has to reach into the next UTC day before the API includes it.
    Mirrors list_reminders()'s dueMin-flooring fix for the same reason."""
    service = _get_service(interactive=interactive)
    if service is None:
        return []
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    resp = service.tasks().list(
        tasklist=tasklist,
        showCompleted=False,
        dueMax=tomorrow.isoformat(),
    ).execute()
    out = [
        {
            "id": t.get("id"),
            "title": t.get("title", ""),
            "due": t.get("due"),
            "notes": t.get("notes", ""),
        }
        for t in resp.get("items") or []
    ]
    out.sort(key=lambda r: r.get("due") or "")
    return out


def complete_reminder(title: str, tasklist: str = "@default") -> Optional[str]:
    """Mark the reminder titled `title` complete (case-insensitive exact
    match, any uncompleted reminder regardless of due date). Returns the
    task ID, or None if no match. Raises ValueError if more than one
    uncompleted reminder matches -- never guesses which one to complete."""
    service = _get_service()
    existing = service.tasks().list(tasklist=tasklist, showCompleted=False).execute()
    title_norm = title.strip().lower()
    matches = [
        t for t in existing.get("items") or []
        if (t.get("title") or "").strip().lower() == title_norm
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"{len(matches)} reminders match {title!r} -- be more specific.")
    task_id = matches[0]["id"]
    service.tasks().patch(tasklist=tasklist, task=task_id, body={"status": "completed"}).execute()
    return task_id
