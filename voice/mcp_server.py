"""MCP server exposing Vesper's voice tools to claude -p.

Run as: python voice/mcp_server.py  (stdio transport — spawned fresh by the
claude CLI per invocation via --mcp-config, not run standalone).

Each tool here is a thin wrapper: the real logic stays in voice/tools/*.py,
voice/memory.py, voice/deadlines.py unchanged. Confirmation-gated tools call
voice.safety.confirm_with_reason() before running, which now reaches the
running UI server (if any) over the HTTP bridge added in voice/ui_server.py,
since this module runs in a separate process spawned fresh per turn."""
from __future__ import annotations

import voice  # noqa: F401 — sys.path setup
from mcp.server.fastmcp import FastMCP

from voice.tools.email import triage_inbox, filter_subscriptions
from voice.tools.search import search_vault
from voice.tools.vault import read_note, append_note, create_note
from voice.tools.workspace import write_draft, write_scratch
from voice.tools.calendar import upcoming_events, create_calendar_event
from voice.tools.pc_control import media_control, set_volume, launch_app, list_windows, focus_window
from voice.memory import remember, forget
from voice.deadlines import complete_deadline
from voice.safety import requires_confirmation, confirm_with_reason
from voice import audit

mcp = FastMCP("vesper")

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


@mcp.tool()
def search_vault_tool(query: str, top_k: int = 5) -> str:
    """Search notes by meaning. Use for any question about saved notes."""
    return search_vault(query=query, top_k=top_k)


@mcp.tool()
def read_note_tool(path: str) -> str:
    """Read a specific vault note by relative path."""
    return read_note(path=path)


@mcp.tool()
def append_note_tool(path: str, text: str) -> str:
    """Append text to an existing vault note. Requires user confirmation."""
    denial = _confirm_gate("append_note", {"path": path, "text": text})
    if denial is not None:
        return denial
    return append_note(path=path, text=text)


@mcp.tool()
def create_note_tool(path: str, text: str) -> str:
    """Create a new vault note. Requires user confirmation."""
    denial = _confirm_gate("create_note", {"path": path, "text": text})
    if denial is not None:
        return denial
    return create_note(path=path, text=text)


@mcp.tool()
def write_draft_tool(name: str, text: str) -> str:
    """Write (create or overwrite) a draft under drafts/active/ for later
    review. Does NOT require confirmation — nothing is sent or finalized."""
    return write_draft(name=name, text=text)


@mcp.tool()
def write_scratch_tool(path: str, text: str) -> str:
    """Write (create or overwrite) a file under scratch/ — Vesper's own
    working space. Does NOT require confirmation."""
    return write_scratch(path=path, text=text)


@mcp.tool()
def upcoming_events_tool(days: int = 7) -> str:
    """Fetch upcoming Google Calendar events."""
    return upcoming_events(days=days)


@mcp.tool()
def remember_fact_tool(key: str, value: str) -> str:
    """Remember a fact across sessions."""
    return remember(key=key, value=value)


@mcp.tool()
def forget_fact_tool(key: str) -> str:
    """Remove a remembered fact. Requires user confirmation."""
    denial = _confirm_gate("forget_fact", {"key": key})
    if denial is not None:
        return denial
    return forget(key=key)


@mcp.tool()
def complete_deadline_tool(query: str) -> str:
    """Mark a deadline as completed — moves its row from Active to Done in
    DEADLINES.md so alerts stop. Requires user confirmation. `query` is a
    few words from the deadline title."""
    denial = _confirm_gate("complete_deadline", {"query": query})
    if denial is not None:
        return denial
    return complete_deadline(query=query)


@mcp.tool()
def triage_inbox_tool(days: int = 3) -> str:
    """Check email inbox for urgent messages."""
    return triage_inbox(days=days)


@mcp.tool()
def filter_subscriptions_tool(days: int = 3) -> str:
    """Identify newsletter/subscription emails."""
    return filter_subscriptions(days=days)


@mcp.tool()
def create_calendar_event_tool(title: str, date: str, description: str = "") -> str:
    """Create an all-day Google Calendar event. Requires user confirmation.
    Args: title(str), date(str, YYYY-MM-DD), description(str, optional)."""
    denial = _confirm_gate("create_calendar_event", {"title": title, "date": date, "description": description})
    if denial is not None:
        return denial
    return create_calendar_event(title=title, date=date, description=description)


@mcp.tool()
def media_control_tool(action: str) -> str:
    """Control media playback/volume via simulated keys. Args: action(str) —
    one of play_pause, next, prev, volume_up, volume_down, mute."""
    return media_control(action=action)


@mcp.tool()
def set_volume_tool(level: int) -> str:
    """Set system output volume to an absolute percentage. Args: level(int, 0-100)."""
    return set_volume(level=level)


@mcp.tool()
def launch_app_tool(name: str) -> str:
    """Launch a configured application by name. Only apps listed in the
    user's pc_control_apps config may be launched. Args: name(str)."""
    return launch_app(name=name)


@mcp.tool()
def list_windows_tool() -> str:
    """List titles of currently visible windows on the desktop."""
    return list_windows()


@mcp.tool()
def focus_window_tool(name: str) -> str:
    """Bring a window to the foreground by matching part of its title. Args: name(str)."""
    return focus_window(name=name)


if __name__ == "__main__":
    mcp.run()
