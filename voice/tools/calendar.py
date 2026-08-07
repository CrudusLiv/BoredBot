"""Calendar tool: upcoming Google Calendar events."""
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
