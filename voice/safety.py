"""Confirmation gate for tools that can modify the vault or take real action.

Tools listed in config.json `requires_confirmation` must be approved before
brain.py dispatches them. Approval is routed, in order:
  1. kill switch paused        -> auto-deny
  2. HTTP bridge to ui_server  -> in-orb approve/deny card (voice/confirm.py),
                                   reachable whether this call runs in-process
                                   (voice/agent_tools.py, today) or from a
                                   separate subprocess
  3. frozen .exe               -> tkinter dialog
  4. console                   -> [y/N] prompt
Every path times out to DENY after `confirm_timeout_seconds` so a
heartbeat-initiated action can never hang waiting on an absent human.
"""
from __future__ import annotations

import json
import threading


def requires_confirmation(tool_name: str) -> bool:
    """Return True if this tool name needs user approval before running."""
    from voice import config as cfg
    gate: list[str] = cfg.load().get("requires_confirmation", [])
    return tool_name in gate


def prompt_confirm(tool_name: str, args: dict) -> bool:
    """Back-compat boolean wrapper around confirm_with_reason()."""
    approved, _reason = confirm_with_reason(tool_name, args)
    return approved


def confirm_with_reason(tool_name: str, args: dict) -> tuple[bool, str]:
    """Confirm a tool call. Returns (approved, reason) where reason is one of
    'user' (approved), 'cancelled' (denied by user), 'timeout', 'paused'."""
    import sys
    from voice import config as cfg, killswitch

    if killswitch.is_paused():
        return False, "paused"

    timeout_s = float(cfg.load().get("confirm_timeout_seconds", 30))

    args_str = json.dumps(args, ensure_ascii=False)
    if len(args_str) > 80:
        args_str = args_str[:77] + "..."

    # HTTP bridge to the running UI server — works whether this call happens
    # in-process (voice/agent_tools.py, today) or from a separate subprocess
    # (a historical mcp_server.py design this stayed compatible with). Falls
    # through to the tkinter/console paths on any failure: server not
    # running (ui_enabled=False), wrong/missing token, or no client
    # connected to hear the confirm card (server-side has_clients() check).
    result = _http_confirm(tool_name, args, timeout_s)
    if result is not None:
        return result

    if getattr(sys, "frozen", False):
        return _tkinter_confirm(tool_name, args_str, timeout_s)

    return _console_confirm(tool_name, args_str, timeout_s)


def _http_confirm(tool_name: str, args: dict, timeout_s: float) -> tuple[bool, str] | None:
    """Try the internal HTTP bridge; return None (not True/False) to signal
    "couldn't reach it, fall back" as distinct from an actual denial."""
    import json as _json
    import os
    import urllib.request
    from voice import config as cfg

    port = cfg.load().get("ui_port", 7070)
    token = os.environ.get("VESPER_UI_TOKEN", "")
    if not token:
        return None
    payload = _json.dumps({
        "tool": tool_name, "args": args, "timeout_s": timeout_s,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/internal/confirm",
        data=payload,
        headers={"Content-Type": "application/json", "X-Vesper-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 2) as resp:
            data = _json.loads(resp.read())
        approved = bool(data["approved"])
        if approved:
            return True, "user"
        return False, ("timeout" if data["reason"] == "timeout" else "cancelled")
    except Exception:
        return None


def _tkinter_confirm(tool_name: str, args_str: str, timeout_s: float) -> tuple[bool, str]:
    """GUI dialog in a daemon thread; deny if the user doesn't answer in time.
    A late click on the orphaned dialog is discarded."""
    result: dict = {}
    done = threading.Event()

    def _ask() -> None:
        try:
            from tkinter import messagebox
            result["approved"] = messagebox.askyesno(
                "Vesper — confirm", f"{tool_name}({args_str})\n\nProceed?"
            )
        except Exception:
            result["approved"] = False
        done.set()

    threading.Thread(target=_ask, daemon=True).start()
    if not done.wait(timeout_s):
        return False, "timeout"
    return (True, "user") if result.get("approved") else (False, "cancelled")


def _console_confirm(tool_name: str, args_str: str, timeout_s: float) -> tuple[bool, str]:
    """Console [y/N] with a deadline. Uses msvcrt polling on Windows so no
    orphaned thread is left holding stdin after a timeout."""
    print(f"\n  [confirm] {tool_name}({args_str})")
    print(f"  proceed? [y/N] ({int(timeout_s)}s) ", end="", flush=True)

    try:
        import msvcrt
        import time as _time
        deadline = _time.monotonic() + timeout_s
        buf = ""
        while _time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwche()
                if ch in ("\r", "\n"):
                    print()
                    answer = buf.strip().lower()
                    if answer in ("y", "yes"):
                        return True, "user"
                    return False, "cancelled"
                if ch == "\x03":  # Ctrl-C
                    print()
                    return False, "cancelled"
                if ch == "\x08":  # backspace
                    buf = buf[:-1]
                else:
                    buf += ch
            else:
                _time.sleep(0.05)
        print("\n  [confirm] timed out — denied")
        return False, "timeout"
    except ImportError:
        pass

    # Non-Windows fallback: input() in a daemon thread with a deadline.
    result: dict = {}
    done = threading.Event()

    def _ask() -> None:
        try:
            result["answer"] = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            result["answer"] = ""
        done.set()

    threading.Thread(target=_ask, daemon=True).start()
    if not done.wait(timeout_s):
        print("\n  [confirm] timed out — denied")
        return False, "timeout"
    if result.get("answer") in ("y", "yes"):
        return True, "user"
    return False, "cancelled"
