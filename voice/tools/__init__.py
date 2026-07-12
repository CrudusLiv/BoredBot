"""Tool registry for Vesper voice assistant.

Tools are registered with _register(name, description, fn).
brain.py reads REGISTRY for the tool protocol and calls dispatch() on hits.
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
from voice.tools.calendar import upcoming_events
from voice.memory import remember, forget

_register("triage_inbox",
    "Check email inbox for urgent messages. Use when asked about email, inbox, or messages. Args: days(int, default 3).",
    triage_inbox)
_register("filter_subscriptions",
    "Identify newsletter/subscription emails. Args: days(int, default 3).",
    filter_subscriptions)
_register("search_vault",
    "Search notes and lectures by meaning. Use for any question about saved notes. Args: query(str), top_k(int, default 5).",
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
_register("remember_fact",
    "Remember a fact across sessions. Args: key(str), value(str).",
    remember)
_register("forget_fact",
    "Remove a remembered fact. REQUIRES CONFIRMATION. Args: key(str).",
    forget)
from voice.tools.launch_app import launch_app as _launch_app_fn
_register("launch_app",
    "Open an app or set of apps by shortcut name. Use when asked to open, launch, or start an app. Args: name(str).",
    _launch_app_fn)
from voice.tools.activate_profile import activate_profile
_register("activate_profile",
    "Activate a named app-launch profile (a pre-defined group of apps), e.g. 'start study mode'. "
    "REQUIRES CONFIRMATION — approving launches every app in the profile in one step. Args: name(str).",
    activate_profile)
from voice.tools.profile_state import update_profile_app_state
_register("update_profile_app_state",
    "Set the working directory an app should open in next time a profile launches it. "
    "Use when asked to remember/change where an app opens for a profile. "
    "Args: profile(str), alias(str), cwd(str).",
    update_profile_app_state)
from voice.deadlines import complete_deadline
_register("complete_deadline",
    "Mark a deadline as completed — moves its row from Active to Done in DEADLINES.md "
    "so alerts stop. REQUIRES CONFIRMATION. Args: query(str) — a few words from the deadline title.",
    complete_deadline)
from voice.tools.study import grade_card_tool, review_cards
_register("review_cards",
    "Fetch spaced-repetition flashcards due for review today. Use when asked to 'quiz me' "
    "or 'review flashcards'. Ask each question aloud, listen to the answer, then call grade_card. No args.",
    review_cards)
_register("grade_card",
    "Record whether the user answered a review card correctly, after you've judged their spoken "
    "answer against the card's stored answer. Args: card_id(str), correct(bool).",
    grade_card_tool)
