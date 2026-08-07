"""Tool registry for Vesper voice assistant.

Tools are registered with _register(name, description, fn). brain.py reads
REGISTRY/_tool_descriptions() to build the system prompt's tool list, but
does NOT call dispatch() here for live tool calls — those go through
voice/mcp_server.py, a separate hand-wired @mcp.tool() server that
voice/llm.py::stream_mcp() spawns as a subprocess for claude -p's native
MCP tool calling. Adding a tool to this registry alone does not make it
callable in conversation; it must also get an @mcp.tool() wrapper in
mcp_server.py.
"""
from __future__ import annotations
import json
from typing import Any
import voice  # noqa: F401

REGISTRY: list[dict] = []
_TOOLS: dict[str, Any] = {}
_DESCRIPTIONS: list[str] = []


def _register(name: str, description: str, fn: Any) -> None:
    REGISTRY.append({"name": name, "description": description})
    _TOOLS[name] = fn
    _DESCRIPTIONS.append(f"- {name}: {description}")


def _tool_descriptions() -> str:
    return "\n".join(_DESCRIPTIONS)


def dispatch(name: str, inputs: dict) -> str:
    fn = _TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name!r}"})
    try:
        result = fn(**inputs)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Register tools ─────────────────────────────────────────────────────────────
from voice.tools.email import triage_inbox, filter_subscriptions
from voice.tools.search import search_vault
from voice.tools.vault import read_note, append_note, create_note
from voice.tools.workspace import write_draft, write_scratch
from voice.tools.calendar import upcoming_events, create_calendar_event
from voice.tools.pc_control import media_control, set_volume, launch_app, list_windows, focus_window
from voice.memory import remember, forget

_register("triage_inbox",
    "Check email inbox for urgent messages. Use when asked about email, inbox, or messages. Args: days(int, default 3).",
    triage_inbox)
_register("filter_subscriptions",
    "Identify newsletter/subscription emails. Args: days(int, default 3).",
    filter_subscriptions)
_register("search_vault",
    "Search notes by meaning. Use for any question about saved notes. Args: query(str), top_k(int, default 5).",
    search_vault)
_register("read_note",
    "Read a specific vault note by relative path. Args: path(str).",
    read_note)
_register("append_note",
    "Append text to an existing vault note. REQUIRES CONFIRMATION. Args: path(str), text(str).",
    append_note)
_register("create_note",
    "Create a new vault note. REQUIRES CONFIRMATION. Args: path(str), text(str).",
    create_note)
_register("write_draft",
    "Write (create or overwrite) a draft under drafts/active/ for later review. Does NOT require confirmation — nothing is sent or finalized. Args: name(str), text(str).",
    write_draft)
_register("write_scratch",
    "Write (create or overwrite) a file under scratch/ — Vesper's own working space, not indexed by note-search. Does NOT require confirmation. Args: path(str), text(str).",
    write_scratch)
_register("upcoming_events",
    "Fetch upcoming Google Calendar events. Args: days(int, default 7).",
    upcoming_events)
_register("create_calendar_event",
    "Create an all-day Google Calendar event. REQUIRES CONFIRMATION. "
    "Args: title(str), date(str, YYYY-MM-DD), description(str, optional).",
    create_calendar_event)
_register("remember_fact",
    "Remember a fact across sessions. Args: key(str), value(str).",
    remember)
_register("forget_fact",
    "Remove a remembered fact. REQUIRES CONFIRMATION. Args: key(str).",
    forget)
from voice.deadlines import complete_deadline
_register("complete_deadline",
    "Mark a deadline as completed — moves its row from Active to Done in DEADLINES.md "
    "so alerts stop. REQUIRES CONFIRMATION. Args: query(str) — a few words from the deadline title.",
    complete_deadline)
_register("media_control",
    "Control media playback/volume via simulated keys. Args: action(str) — one of "
    "play_pause, next, prev, volume_up, volume_down, mute.",
    media_control)
_register("set_volume",
    "Set system output volume to an absolute percentage. Args: level(int, 0-100).",
    set_volume)
_register("launch_app",
    "Launch a configured application by name. Only apps listed in the user's "
    "pc_control_apps config may be launched — anything else is refused. Args: name(str).",
    launch_app)
_register("list_windows",
    "List titles of currently visible windows on the desktop.",
    list_windows)
_register("focus_window",
    "Bring a window to the foreground by matching part of its title. Args: name(str).",
    focus_window)
