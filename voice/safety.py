"""Confirmation gate for tools that can modify the vault or take real action.

Tools listed in config.json `requires_confirmation` must be approved before
brain.py dispatches them. Approval is routed, in order:
  1. kill switch paused        -> auto-deny
  2. orb UI has clients        -> in-orb approve/deny card (voice/confirm.py)
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

    # Orb UI path — only when at least one client is connected to hear it
    try:
        from voice import ui_server
        ui_connected = ui_server.has_clients()
    except Exception:
        ui_connected = False
    if ui_connected:
        from voice import confirm as _confirm
        approved, reason = _confirm.request(tool_name, args, timeout_s)
        if approved:
            return True, "user"
        return False, ("timeout" if reason == "timeout" else "cancelled")

    if getattr(sys, "frozen", False):
        return _tkinter_confirm(tool_name, args_str, timeout_s)

    return _console_confirm(tool_name, args_str, timeout_s)


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
