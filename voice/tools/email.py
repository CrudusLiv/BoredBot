"""Email tools: triage inbox, filter subscriptions. Read-only."""
from __future__ import annotations
import voice  # noqa: F401

_URGENT = ["urgent", "asap", "deadline", "overdue", "action required",
           "respond by", "reply needed", "important", "follow up"]
_SUB = ["unsubscribe", "newsletter", "noreply", "no-reply",
        "marketing", "promo", "notification", "digest", "weekly"]


def triage_inbox(days: int = 3) -> str:
    try:
        from integrations import gmail_int  # type: ignore
        emails = gmail_int.list_recent(days=days, max_results=50)
    except Exception as exc:
        return f"Gmail unavailable: {exc}"
    if not emails:
        return f"No emails in the last {days} day(s)."
    urgent_idx = set()
    for i, e in enumerate(emails):
        subj = (e.get("subject") or "").lower()
        snip = (e.get("snippet") or "").lower()
        if any(k in subj or k in snip for k in _URGENT):
            urgent_idx.add(i)
    lines = [f"{len(emails)} email(s) in last {days}d — {len(urgent_idx)} flagged urgent."]
    for i, e in enumerate(emails):
        frm = (e.get("from") or "?")
        subj = (e.get("subject") or "(no subject)")
        date = (e.get("date") or "")
        snip = (e.get("snippet") or "")
        flag = "!" if i in urgent_idx else " "
        lines.append(f"[{flag}] {date}  {frm}  —  {subj}")
        if snip:
            lines.append(f"     {snip[:120]}")
    return "\n".join(lines)


def filter_subscriptions(days: int = 3) -> str:
    try:
        from integrations import gmail_int  # type: ignore
        emails = gmail_int.list_recent(days=days, max_results=30)
    except Exception as exc:
        return f"Gmail unavailable: {exc}"
    subs = [
        e for e in emails
        if any(k in (e.get("from") or "").lower() or
               k in (e.get("snippet") or "").lower() for k in _SUB)
    ]
    if not subs:
        return "No obvious subscription emails found."
    senders = list({(e.get("from") or "?")[:50] for e in subs})[:8]
    return f"{len(subs)} subscription-type emails from: {', '.join(senders)}"
