"""Web feed store — append-only log of heartbeat outputs for the Alerts panel.

JSON at .claude/data/state/feed.json. Path resolved lazily from
CLAUDE_PROJECT_DIR on every call so tests that monkeypatch the env var
isolate cleanly. A module-level lock serialises read-modify-write."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_KL = timezone(timedelta(hours=8))
_LOCK = threading.Lock()
MAX_RECORDS = 50

_PRIORITY_MAP: dict[str, str] = {
    "deadline_overdue": "urgent",
    "error": "urgent",
    "deadline_24h": "high",
    "deadline_72h": "normal",
    "heartbeat_tick": "normal",
    "next3": "normal",
}


def _store_path() -> Path:
    proj = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return proj / ".claude" / "data" / "state" / "feed.json"


def _read() -> list[dict]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write(records: list[dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _feed_priority(kind: str) -> str:
    return _PRIORITY_MAP.get(kind, "low")


def _feed_title_body(kind: str, payload: dict) -> tuple[str, str]:
    """Extract a (title, body) pair from a dashboard payload."""
    if kind in ("deadline_72h", "deadline_24h", "deadline_overdue"):
        course = (payload.get("course") or "").strip()
        title = (payload.get("title") or "(untitled)").strip()
        due = payload.get("due") or "?"
        tag = f"[{course}] " if course else ""
        return f"{tag}{title}", f"due {due}"

    if kind == "next3":
        items = payload.get("items") or []
        titles = [i.get("title", "") for i in items[:3]]
        return "Next 3 deadlines", ", ".join(t for t in titles if t) or "—"

    if kind == "lecture_new":
        title = (payload.get("title") or "(untitled)").strip()
        name = (payload.get("name") or "").strip()
        tldr = payload.get("tldr") or []
        body = f"{name} — {tldr[0]}" if name and tldr else (name or (tldr[0] if tldr else ""))
        return title, body

    if kind == "morning_digest":
        ts = payload.get("ts")
        now = datetime.fromtimestamp(ts, tz=_KL) if ts else datetime.now(_KL)
        return f"Morning — {now.strftime('%a %d %b')}", (payload.get("body") or "")[:200]

    if kind == "evening_nudge":
        return "Evening nudge", (payload.get("body") or "")[:200]

    if kind == "daily_digest":
        return (payload.get("title") or "Daily digest"), (payload.get("body") or "")[:200]

    if kind == "heartbeat_tick":
        failing = payload.get("failing") or []
        body = f"failing: {', '.join(failing)}" if failing else "check system"
        return "System degraded", body

    if kind == "error":
        script = payload.get("script") or "unknown"
        trace = (payload.get("trace") or "")[:150]
        return f"Error in {script}", trace

    if kind in ("pr_opened", "pr_merged", "pr_comment"):
        repo = (payload.get("repo") or "").strip()
        pr_num = payload.get("pr_number")
        pr_title = (payload.get("pr_title") or "").strip()
        ref = f"#{pr_num}" if pr_num else ""
        heading = " — ".join(p for p in (repo, ref) if p) or kind
        return heading, pr_title

    # inbox_*, idea, email_*, fallback
    return (payload.get("title") or kind), (payload.get("body") or "")[:200]


def append(kind: str, payload: dict) -> dict:
    """Prepend a new feed record and trim to MAX_RECORDS. Returns the new record."""
    now = datetime.now(_KL).isoformat()
    title, body = _feed_title_body(kind, payload)
    record = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "title": title,
        "body": body,
        "priority": _feed_priority(kind),
        "read": False,
        "ts": payload.get("ts"),
        "created_at": now,
        "updated_at": now,
    }
    with _LOCK:
        records = _read()
        records.insert(0, record)
        _write(records[:MAX_RECORDS])
    return record


def mark_read(item_id: str) -> dict | None:
    """Set read=True on the record with the given id. Returns updated record or None."""
    with _LOCK:
        records = _read()
        for rec in records:
            if rec["id"] == item_id:
                rec["read"] = True
                rec["updated_at"] = datetime.now(_KL).isoformat()
                _write(records)
                return rec
    return None


def recent(limit: int = MAX_RECORDS) -> list[dict]:
    """Return up to limit records, newest first."""
    with _LOCK:
        return _read()[:limit]
