"""In-process tools for the Claude Agent SDK — replaces voice/mcp_server.py.

Each tool has two parts: a plain sync function (same name, same body as the
old FastMCP wrapper) that does the confirmation gate and delegates to the
real logic in voice/tools/*.py, voice/memory.py, voice/deadlines.py; and a
thin async adapter, built by _sdk_tool(), that the SDK calls directly in
this process — no subprocess, no stdio handshake. Confirmation-gated tools
call voice.safety.confirm_with_reason(), which reaches the running UI
server over the same HTTP bridge it always used.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from claude_agent_sdk import tool, create_sdk_mcp_server

import voice  # noqa: F401 — sys.path setup
from voice.tools.email import triage_inbox, filter_subscriptions
from voice.tools.search import search_vault
from voice.tools.vault import read_note, append_note, create_note
from voice.tools.workspace import write_draft, write_scratch
from voice.tools.finance import log_expense, log_income
from voice.tools.calendar import (
    upcoming_events, create_calendar_event, delete_calendar_event,
    create_reminder, upcoming_reminders, complete_reminder,
)
from voice.tools.pc_control import media_control, set_volume, launch_app, list_windows, focus_window
from voice.tools.filesearch import find_files, search_files
from voice.memory import remember, forget
from voice.deadlines import complete_deadline
from voice.safety import requires_confirmation, confirm_with_reason
from voice import audit

_DENY_MESSAGES = {
    "cancelled": "[cancelled by user]",
    "timeout": "[denied — confirmation timed out; do not retry, mention it needs approval]",
    "paused": "[blocked — Vesper is paused; do not retry until resumed]",
}


def _confirm_gate(name: str, args: dict) -> str | None:
    """Return a denial string if this tool needs and lacks confirmation,
    else None (caller proceeds to run the real tool)."""
    if not requires_confirmation(name):
        return None
    approved, reason = confirm_with_reason(name, args)
    if approved:
        return None
    result = _DENY_MESSAGES.get(reason, "[cancelled by user]")
    audit.log("tool", result, tool_name=name, outcome=reason)
    return result


def search_vault_tool(query: str, top_k: int = 5) -> str:
    """Search notes by meaning. Use for any question about saved notes."""
    return search_vault(query=query, top_k=top_k)


def read_note_tool(path: str) -> str:
    """Read a specific vault note by relative path."""
    return read_note(path=path)


def append_note_tool(path: str, text: str) -> str:
    """Append text to an existing vault note. Requires user confirmation."""
    denial = _confirm_gate("append_note", {"path": path, "text": text})
    if denial is not None:
        return denial
    return append_note(path=path, text=text)


def create_note_tool(path: str, text: str) -> str:
    """Create a new vault note. Requires user confirmation."""
    denial = _confirm_gate("create_note", {"path": path, "text": text})
    if denial is not None:
        return denial
    return create_note(path=path, text=text)


def write_draft_tool(name: str, text: str) -> str:
    """Write (create or overwrite) a draft under drafts/active/ for later
    review. Does NOT require confirmation — nothing is sent or finalized."""
    return write_draft(name=name, text=text)


def log_expense_tool(amount: float, category: str, note: str = "") -> str:
    """Log an expense to this month's finance ledger. Does NOT require
    confirmation. Args: amount(float), category(str, one word),
    note(str, optional)."""
    return log_expense(amount=amount, category=category, note=note)


def log_income_tool(amount: float, category: str, note: str = "") -> str:
    """Log income to this month's finance ledger. Does NOT require
    confirmation. Args: amount(float), category(str, one word),
    note(str, optional)."""
    return log_income(amount=amount, category=category, note=note)


def write_scratch_tool(path: str, text: str) -> str:
    """Write (create or overwrite) a file under scratch/ — Vesper's own
    working space. Does NOT require confirmation."""
    return write_scratch(path=path, text=text)


def upcoming_events_tool(days: int = 7) -> str:
    """Fetch upcoming Google Calendar events."""
    return upcoming_events(days=days)


def upcoming_reminders_tool(days: int = 7) -> str:
    """Fetch upcoming Google Calendar reminders (Tasks API)."""
    return upcoming_reminders(days=days)


def remember_fact_tool(key: str, value: str) -> str:
    """Remember a fact across sessions."""
    return remember(key=key, value=value)


def forget_fact_tool(key: str) -> str:
    """Remove a remembered fact. Requires user confirmation."""
    denial = _confirm_gate("forget_fact", {"key": key})
    if denial is not None:
        return denial
    return forget(key=key)


def complete_deadline_tool(query: str) -> str:
    """Mark a deadline as completed — moves its row from Active to Done in
    DEADLINES.md so alerts stop. Requires user confirmation. `query` is a
    few words from the deadline title."""
    denial = _confirm_gate("complete_deadline", {"query": query})
    if denial is not None:
        return denial
    return complete_deadline(query=query)


def triage_inbox_tool(days: int = 3) -> str:
    """Check email inbox for urgent messages."""
    return triage_inbox(days=days)


def filter_subscriptions_tool(days: int = 3) -> str:
    """Identify newsletter/subscription emails."""
    return filter_subscriptions(days=days)


def create_calendar_event_tool(title: str, date: str, description: str = "") -> str:
    """Create an all-day Google Calendar event. Requires user confirmation.
    Args: title(str), date(str, YYYY-MM-DD), description(str, optional)."""
    denial = _confirm_gate("create_calendar_event", {"title": title, "date": date, "description": description})
    if denial is not None:
        return denial
    return create_calendar_event(title=title, date=date, description=description)


def delete_calendar_event_tool(title: str, date: str) -> str:
    """Delete a Google Calendar event. Requires user confirmation.
    Args: title(str), date(str, YYYY-MM-DD)."""
    denial = _confirm_gate("delete_calendar_event", {"title": title, "date": date})
    if denial is not None:
        return denial
    return delete_calendar_event(title=title, date=date)


def create_reminder_tool(title: str, date: str, description: str = "") -> str:
    """Create a Google Calendar reminder. Requires user confirmation.
    Args: title(str), date(str, YYYY-MM-DD), description(str, optional)."""
    denial = _confirm_gate("create_reminder", {"title": title, "date": date, "description": description})
    if denial is not None:
        return denial
    return create_reminder(title=title, date=date, description=description)


def complete_reminder_tool(title: str) -> str:
    """Mark a reminder done by title. Stops the heartbeat's every-2-hour
    voice nag for that reminder (see voice/heartbeat.py
    _check_reminder_nags). Not confirmation-gated by default -- it's meant
    to be a fast, frictionless way to silence a repeating nag; add
    "complete_reminder" to requires_confirmation in settings if you want
    one anyway."""
    denial = _confirm_gate("complete_reminder", {"title": title})
    if denial is not None:
        return denial
    return complete_reminder(title=title)


def media_control_tool(action: str) -> str:
    """Control media playback/volume via simulated keys. Args: action(str) —
    one of play_pause, next, prev, volume_up, volume_down, mute."""
    return media_control(action=action)


def set_volume_tool(level: int) -> str:
    """Set system output volume to an absolute percentage. Args: level(int, 0-100)."""
    return set_volume(level=level)


def launch_app_tool(name: str) -> str:
    """Launch a configured application by name. Only apps listed in the
    user's pc_control_apps config may be launched. Args: name(str)."""
    return launch_app(name=name)


def list_windows_tool() -> str:
    """List titles of currently visible windows on the desktop."""
    return list_windows()


def focus_window_tool(name: str) -> str:
    """Bring a window to the foreground by matching part of its title. Args: name(str)."""
    return focus_window(name=name)


def find_files_tool(name_glob: str, limit: int = 50) -> str:
    """Find files by name across the configured search roots. Read-only.
    Args: name_glob(str, e.g. "*.pdf", "resume*"), limit(int)."""
    return find_files(name_glob=name_glob, limit=limit)


def search_files_tool(query: str, path_glob: str = "*", limit: int = 50) -> str:
    """Search file contents for a string across the configured search roots.
    Read-only. Args: query(str), path_glob(str, restrict by filename),
    limit(int)."""
    return search_files(query=query, path_glob=path_glob, limit=limit)


# ── SDK registration ────────────────────────────────────────────────────────
# Wrap each sync function above as an async @tool the SDK can call directly
# in this process. asyncio.to_thread() keeps blocking work (file I/O, Google
# API calls, confirm_with_reason()'s HTTP round-trip) off the SDK's event
# loop, so one slow tool call can't stall every other in-flight turn.

def _sdk_tool(name: str, description: str, schema: dict[str, Any], fn: Callable[..., str]):
    @tool(name, description, schema)
    async def _adapter(args: dict) -> dict:
        result = await asyncio.to_thread(fn, **args)
        return {"content": [{"type": "text", "text": result}]}
    return _adapter


_agent_tools = [
    _sdk_tool(
        "search_vault_tool", search_vault_tool.__doc__ or "",
        {"type": "object", "properties": {
            "query": {"type": "string"}, "top_k": {"type": "integer"},
        }, "required": ["query"]},
        search_vault_tool,
    ),
    _sdk_tool(
        "read_note_tool", read_note_tool.__doc__ or "",
        {"path": str},
        read_note_tool,
    ),
    _sdk_tool(
        "append_note_tool", append_note_tool.__doc__ or "",
        {"path": str, "text": str},
        append_note_tool,
    ),
    _sdk_tool(
        "create_note_tool", create_note_tool.__doc__ or "",
        {"path": str, "text": str},
        create_note_tool,
    ),
    _sdk_tool(
        "write_draft_tool", write_draft_tool.__doc__ or "",
        {"name": str, "text": str},
        write_draft_tool,
    ),
    _sdk_tool(
        "write_scratch_tool", write_scratch_tool.__doc__ or "",
        {"path": str, "text": str},
        write_scratch_tool,
    ),
    _sdk_tool(
        "upcoming_events_tool", upcoming_events_tool.__doc__ or "",
        {"type": "object", "properties": {
            "days": {"type": "integer"},
        }, "required": []},
        upcoming_events_tool,
    ),
    _sdk_tool(
        "upcoming_reminders_tool", upcoming_reminders_tool.__doc__ or "",
        {"type": "object", "properties": {
            "days": {"type": "integer"},
        }, "required": []},
        upcoming_reminders_tool,
    ),
    _sdk_tool(
        "remember_fact_tool", remember_fact_tool.__doc__ or "",
        {"key": str, "value": str},
        remember_fact_tool,
    ),
    _sdk_tool(
        "forget_fact_tool", forget_fact_tool.__doc__ or "",
        {"key": str},
        forget_fact_tool,
    ),
    _sdk_tool(
        "complete_deadline_tool", complete_deadline_tool.__doc__ or "",
        {"query": str},
        complete_deadline_tool,
    ),
    _sdk_tool(
        "triage_inbox_tool", triage_inbox_tool.__doc__ or "",
        {"type": "object", "properties": {
            "days": {"type": "integer"},
        }, "required": []},
        triage_inbox_tool,
    ),
    _sdk_tool(
        "filter_subscriptions_tool", filter_subscriptions_tool.__doc__ or "",
        {"type": "object", "properties": {
            "days": {"type": "integer"},
        }, "required": []},
        filter_subscriptions_tool,
    ),
    _sdk_tool(
        "create_calendar_event_tool", create_calendar_event_tool.__doc__ or "",
        {"type": "object", "properties": {
            "title": {"type": "string"}, "date": {"type": "string"},
            "description": {"type": "string"},
        }, "required": ["title", "date"]},
        create_calendar_event_tool,
    ),
    _sdk_tool(
        "delete_calendar_event_tool", delete_calendar_event_tool.__doc__ or "",
        {"type": "object", "properties": {
            "title": {"type": "string"}, "date": {"type": "string"},
        }, "required": ["title", "date"]},
        delete_calendar_event_tool,
    ),
    _sdk_tool(
        "create_reminder_tool", create_reminder_tool.__doc__ or "",
        {"type": "object", "properties": {
            "title": {"type": "string"}, "date": {"type": "string"},
            "description": {"type": "string"},
        }, "required": ["title", "date"]},
        create_reminder_tool,
    ),
    _sdk_tool(
        "complete_reminder_tool", complete_reminder_tool.__doc__ or "",
        {"title": str},
        complete_reminder_tool,
    ),
    _sdk_tool(
        "media_control_tool", media_control_tool.__doc__ or "",
        {"action": str},
        media_control_tool,
    ),
    _sdk_tool(
        "set_volume_tool", set_volume_tool.__doc__ or "",
        {"level": int},
        set_volume_tool,
    ),
    _sdk_tool(
        "launch_app_tool", launch_app_tool.__doc__ or "",
        {"name": str},
        launch_app_tool,
    ),
    _sdk_tool(
        "list_windows_tool", list_windows_tool.__doc__ or "",
        {"type": "object", "properties": {}, "required": []},
        list_windows_tool,
    ),
    _sdk_tool(
        "focus_window_tool", focus_window_tool.__doc__ or "",
        {"name": str},
        focus_window_tool,
    ),
    _sdk_tool(
        "find_files_tool", find_files_tool.__doc__ or "",
        {"type": "object", "properties": {
            "name_glob": {"type": "string"}, "limit": {"type": "integer"},
        }, "required": ["name_glob"]},
        find_files_tool,
    ),
    _sdk_tool(
        "search_files_tool", search_files_tool.__doc__ or "",
        {"type": "object", "properties": {
            "query": {"type": "string"}, "path_glob": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["query"]},
        search_files_tool,
    ),
    _sdk_tool(
        "log_expense_tool", log_expense_tool.__doc__ or "",
        {"type": "object", "properties": {
            "amount": {"type": "number"}, "category": {"type": "string"},
            "note": {"type": "string"},
        }, "required": ["amount", "category"]},
        log_expense_tool,
    ),
    _sdk_tool(
        "log_income_tool", log_income_tool.__doc__ or "",
        {"type": "object", "properties": {
            "amount": {"type": "number"}, "category": {"type": "string"},
            "note": {"type": "string"},
        }, "required": ["amount", "category"]},
        log_income_tool,
    ),
]

vesper_tools = create_sdk_mcp_server(name="vesper", version="1.0.0", tools=_agent_tools)
