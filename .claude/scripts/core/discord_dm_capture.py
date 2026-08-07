"""Section 3: classify and route self-DMs sent to the capture bot.

CrudusLiv DMs a dedicated bot (the same one that powers the Phase 4
read-only cache). Each new DM authored by CrudusLiv is classified:

  note      → append to today's daily/YYYY-MM-DD.md under ## Captured
  finance   → append to finance/YYYY-MM.md under ## Captured
  chit-chat → discard

Classifier is rule-based first; the LLM is only used when the rules
return None (ambiguous). The single LLM call is a Haiku zero-shot
classification — cheap, used rarely.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
VAULT = PROJECT_DIR / "Dynamous" / "Memory"
KL = timezone(timedelta(hours=8))
# Bounds how far back the self-DM scan looks. Matches discord_ping's window
# since they share the seen_message_ids state and that state's TTL.
SEEN_TTL_SEC = 24 * 3600

_FINANCE_RE = re.compile(r"(?:^|(?<=\s))(?:rm|usd|myr|\$)\s*\d+", re.IGNORECASE)
_FINANCE_KEYWORDS = re.compile(
    r"\b(spent|paid|earned|expense|income|salary|invoice)\b",
    re.IGNORECASE,
)
# Explicit opt-in: only count as a note if the message starts with one of
# these markers. Everything else is treated as chit-chat and discarded.
_NOTE_PREFIX_RE = re.compile(
    r"^\s*note(?:\s+to\s+self)?\s*[:\-—,]?\s+\S",
    re.IGNORECASE,
)
# Same prefix, used to strip the marker from the routed body.
_NOTE_PREFIX_STRIP_RE = re.compile(
    r"^\s*note(?:\s+to\s+self)?\s*[:\-—,]?\s+",
    re.IGNORECASE,
)


def classify_rule_based(content: str) -> str:
    """Return 'note' | 'finance' | 'chit-chat'. Deterministic — no None."""
    if not content:
        return "chit-chat"
    text = content.strip()

    # Currency symbol or money keyword → finance.
    if _FINANCE_RE.search(text) or _FINANCE_KEYWORDS.search(text):
        return "finance"

    # Explicit "note" / "note to self" prefix → note.
    if _NOTE_PREFIX_RE.match(text):
        return "note"

    # Everything else is chit-chat and discarded.
    return "chit-chat"


def classify(content: str) -> str:
    return classify_rule_based(content)


def _append(target: Path, header: str, body: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(f"# {target.stem}\n\n", encoding="utf-8")
    text = target.read_text(encoding="utf-8")
    if "## Captured" not in text:
        text = text.rstrip() + "\n\n## Captured\n"
    text = text.rstrip() + f"\n- [{header}] {body}\n"
    target.write_text(text, encoding="utf-8")


_NOTES_SEED = (
    "# Notes\n\n"
    "Rolling file for topic-based notes captured mid-conversation. "
    "Append a new `- YYYY-MM-DD — <topic>` bullet per note "
    "(multi-line bodies indent under the bullet). Don't split into multiple files.\n"
)


def _append_note(target: Path, dt: datetime, raw: str) -> str:
    """Append a `- YYYY-MM-DD — <topic>` bullet to the rolling notes file.

    Multi-line bodies indent under the bullet. Returns the stripped note
    body on success, or empty string if the message is empty after the
    `note:` prefix is stripped (in which case nothing is written).

    Two-step write so the bullet portion goes through vault.actions.append
    and lands in the transaction log -- this is what makes `undo` in
    #inbox reverse a `note:` post."""
    stripped = _NOTE_PREFIX_STRIP_RE.sub("", raw, count=1).strip()
    if not stripped:
        return ""
    lines = stripped.split("\n")
    first = lines[0].strip()
    topic = first
    extra_lines = [ln.rstrip() for ln in lines[1:] if ln.strip()]
    bullet = f"- {dt.strftime('%Y-%m-%d')} — {topic}\n"
    if extra_lines:
        bullet += "\n".join("  " + ln for ln in extra_lines) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(_NOTES_SEED, encoding="utf-8")
    text = target.read_text(encoding="utf-8")
    trimmed = text.rstrip()
    last_line = trimmed.rsplit("\n", 1)[-1].lstrip()
    sep = "\n" if last_line.startswith(("- ", "  ")) else "\n\n"
    # Step 1: normalize the file's tail (rstrip + separator). NOT logged --
    # this is bookkeeping, not the actual note write.
    target.write_text(trimmed + sep, encoding="utf-8")
    # Step 2: append the bullet via vault.actions so the transaction log
    # gets an entry and `undo` can truncate it back off.
    try:
        from vault import actions
        rel = target.relative_to(VAULT).as_posix()
        actions.append(rel, bullet)
    except Exception as exc:
        # If the vault module isn't importable (very early bootstrap) or
        # paths.validate rejects the path, fall back to a plain append so
        # the note still lands -- just won't be undoable.
        print(f"_append_note: action-logged append failed ({exc}); falling back", file=sys.stderr)
        with target.open("a", encoding="utf-8") as f:
            f.write(bullet)
    return stripped


def route(msg: dict, *, label: Optional[str] = None) -> str:
    """Route a DM dict to its destination. Returns the label used."""
    if label is None:
        label = classify(msg.get("content") or "")
    if label == "chit-chat":
        return label
    dt = datetime.fromtimestamp(float(msg.get("created_at") or time.time()), tz=KL)
    raw = (msg.get("content") or "").strip()
    if label == "finance":
        target = VAULT / "finance" / f"{dt.strftime('%Y-%m')}.md"
        _append(target, dt.strftime("%H:%M"), raw.replace("\n", " "))
    elif label == "note":
        _append_note(VAULT / "notes" / "NOTES.md", dt, raw)
    return label


STATE_PATH = PROJECT_DIR / ".claude" / "data" / "discord_last_tick.json"


def route_and_mark(msg: dict, state_path: Path | None = None) -> str:
    """Route a single DM and immediately mark it seen so the heartbeat skips it."""
    import json
    label = route(msg)
    sp = state_path or STATE_PATH
    state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {
        "last_tick": None, "seen_message_ids": [],
    }
    state.setdefault("seen_message_ids", []).append({
        "id": msg.get("id"), "t": msg.get("created_at") or time.time(),
    })
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return label


def scan_and_route(
    db_path: Path,
    *,
    user_id: str,
    state_path: Path,
    bot_dm_channel_id: Optional[str] = None,
    now: Optional[float] = None,
) -> dict[str, int]:
    """Find new self-DMs sent to the capture bot, classify, and route.

    Shares state_path with discord_ping (seen_message_ids covers both).
    bot_dm_channel_id, if provided, restricts the scan to that channel.
    Only self-DMs from the last SEEN_TTL_SEC are considered -- older ones
    are ignored to match the shared seen-state TTL and avoid re-processing
    history each time scan_pings reaps an entry."""
    import json
    if now is None:
        now = time.time()
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "last_tick": None, "seen_message_ids": [],
    }
    seen = {s["id"] for s in state.get("seen_message_ids") or []}

    if not db_path.exists():
        return {"note": 0, "finance": 0, "chit-chat": 0}

    cutoff = now - SEEN_TTL_SEC
    sql = """
        SELECT id, channel_id, content, created_at
        FROM messages
        WHERE is_dm = 1 AND is_self = 1 AND created_at >= ?
    """
    params: list = [cutoff]
    if bot_dm_channel_id:
        sql += " AND channel_id = ?"
        params.append(bot_dm_channel_id)
    sql += " ORDER BY created_at ASC"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()

    counts = {"note": 0, "finance": 0, "chit-chat": 0}
    for r in rows:
        if r["id"] in seen:
            continue
        label = route(r)
        counts[label] = counts.get(label, 0) + 1
        state.setdefault("seen_message_ids", []).append({"id": r["id"], "t": r["created_at"]})

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return counts
