"""Calendar tool: upcoming Google Calendar events, creating new ones."""
from __future__ import annotations
import voice  # noqa: F401


def upcoming_events(days: int = 7) -> str:
    try:
        from integrations import gcal_int  # type: ignore
        events = gcal_int.upcoming(days=days)
        if not events:
            return f"No events in the next {days} day(s)."
        lines = [f"{len(events)} event(s) in the next {days} day(s):"]
        for e in events[:10]:
            start = e.get("start", "?")
            summary = e.get("summary", "?")
            lines.append(f"  {start}: {summary}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Calendar unavailable: {exc}"


def create_calendar_event(title: str, date: str, description: str = "") -> str:
    """Create an all-day Google Calendar event. Args: title(str),
    date(str, YYYY-MM-DD), description(str, optional). Deduped by
    gcal_write.create_event on (title, date) — a matching existing event
    is reported, not silently skipped or duplicated."""
    try:
        from integrations import gcal_write  # type: ignore
        event_id = gcal_write.create_event(title, date, description=description)
    except Exception as exc:
        return f"Calendar unavailable: {exc}"
    if event_id is None:
        return f"An event titled {title!r} already exists on {date} — didn't create a duplicate."
    return f"Created calendar event {title!r} on {date}."


def delete_calendar_event(title: str, date: str) -> str:
    """Delete a Google Calendar event by title + date. Reports "no event
    found" or "can't delete — N events match" rather than silently picking
    one or raising to the caller."""
    try:
        from integrations import gcal_write  # type: ignore
        event_id = gcal_write.delete_event(title, date)
    except ValueError as exc:
        return f"Can't delete — {exc}"
    except Exception as exc:
        return f"Calendar unavailable: {exc}"
    if event_id is None:
        return f"No event titled {title!r} found on {date}."
    return f"Deleted calendar event {title!r} on {date}."


def create_reminder(title: str, date: str, description: str = "") -> str:
    """Create a Google Calendar reminder (via the Tasks API). Deduped by
    gtasks_write.create_reminder on (title, date) -- a matching existing
    reminder is reported, not silently skipped or duplicated."""
    try:
        from integrations import gtasks_write  # type: ignore
        task_id = gtasks_write.create_reminder(title, date, description=description)
    except Exception as exc:
        return f"Reminders unavailable: {exc}"
    if task_id is None:
        return f"A reminder titled {title!r} already exists on {date}."
    return f"Created reminder {title!r} on {date}."


def upcoming_reminders(days: int = 7) -> str:
    try:
        from integrations import gtasks_write  # type: ignore
        reminders = gtasks_write.list_reminders(days=days)
    except Exception as exc:
        return f"Reminders unavailable: {exc}"
    if not reminders:
        return f"No reminders due in the next {days} day(s)."
    lines = [f"{len(reminders)} reminder(s) due in the next {days} day(s):"]
    for r in reminders[:10]:
        due = r.get("due", "?")
        title = r.get("title", "?")
        lines.append(f"  {due}: {title}")
    return "\n".join(lines)
