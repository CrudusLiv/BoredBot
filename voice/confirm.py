"""In-UI confirmation bridge between the brain worker thread and the orb.

The brain thread calls request() and blocks on an Event; the FastAPI thread
resolves it via resolve() when the user clicks approve/deny in the orb.
Every request times out to DENY so a heartbeat-initiated action can never
hang the loop waiting on a human who isn't there.
"""
from __future__ import annotations

import json
import threading
import uuid


class _Pending:
    __slots__ = ("id", "tool", "args_summary", "decided", "approved", "reason")

    def __init__(self, id_: str, tool: str, args_summary: str) -> None:
        self.id = id_
        self.tool = tool
        self.args_summary = args_summary
        self.decided = threading.Event()
        self.approved = False
        self.reason = "timeout"


_PENDING: dict[str, _Pending] = {}
_pending_lock = threading.Lock()


def _emit(event: dict) -> None:
    try:
        from voice import ui_server
        ui_server.post_event(event)
    except Exception:
        pass


def request(tool: str, args: dict, timeout_s: float) -> tuple[bool, str]:
    """Ask connected UI clients to approve a tool call. Blocks the calling
    (brain worker) thread until resolved or timeout. Returns (approved, reason)
    where reason is 'user' or 'timeout'."""
    args_summary = json.dumps(args, ensure_ascii=False)
    if len(args_summary) > 120:
        args_summary = args_summary[:117] + "..."

    pending = _Pending(uuid.uuid4().hex[:8], tool, args_summary)
    with _pending_lock:
        _PENDING[pending.id] = pending

    try:
        _emit({
            "type": "confirm",
            "id": pending.id,
            "tool": tool,
            "args_summary": args_summary,
            "timeout_s": timeout_s,
        })
        if not pending.decided.wait(timeout_s):
            pending.reason = "timeout"
            pending.approved = False
            _emit({
                "type": "confirm_resolved",
                "id": pending.id,
                "approved": False,
                "reason": "timeout",
            })
        return pending.approved, pending.reason
    finally:
        with _pending_lock:
            _PENDING.pop(pending.id, None)


def resolve(id_: str, approve: bool) -> bool:
    """Resolve a pending confirmation (called from the FastAPI thread).
    Returns False if the id is unknown or already expired."""
    with _pending_lock:
        pending = _PENDING.get(id_)
        if pending is None or pending.decided.is_set():
            return False
        pending.approved = approve
        pending.reason = "user"
        pending.decided.set()
    _emit({
        "type": "confirm_resolved",
        "id": id_,
        "approved": approve,
        "reason": "user",
    })
    return True
