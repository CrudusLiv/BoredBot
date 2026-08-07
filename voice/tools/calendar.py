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
