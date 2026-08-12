"""Google Calendar Reminders -- backed by the Google Tasks API (Calendar's
own "Reminders" toggle is a Tasks-API view, not a Calendar-API resource).

Public API:
    create_reminder(title, date, description="", tasklist="@default") -> task_id | None
    list_reminders(days=7, tasklist="@default") -> [{"id","title","due","notes"}, ...]

Dedup is by (title, date) on the given task list, case-insensitive. If a
matching reminder already exists, create_reminder() returns None and does
NOT insert.

No delete function -- only creation and listing are supported here.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])


def _get_service():
    """Return an authorised Google Tasks v1 client. Lazy import so tests
    can monkey-patch this without pulling in google-api-python-client."""
    sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts" / "integrations"))
    from google_auth import get_credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    creds = get_credentials()
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


def list_reminders(days: int = 7, tasklist: str = "@default") -> list[dict]:
    """List uncompleted reminders due within the next `days` days on
    `tasklist`, sorted by due date. Returns
    [{"id", "title", "due", "notes"}, ...]."""
    service = _get_service()
    now = datetime.now(timezone.utc)
    later = now + timedelta(days=days)
    resp = service.tasks().list(
        tasklist=tasklist,
        showCompleted=False,
        dueMin=now.isoformat(),
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
