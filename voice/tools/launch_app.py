"""launch_app tool — opens approved apps (voice.approved_apps)."""
from __future__ import annotations

import json
import subprocess
import sys


def launch_app(name: str) -> str:
    from voice import approved_apps

    approved: dict = approved_apps.get_approved()
    key = next((k for k in approved if k.lower() == name.lower()), None)
    if key is not None:
        return _run([approved[key]])

    available = ", ".join(sorted(approved.keys())) or "none approved yet — scan and approve apps in the settings panel"
    return json.dumps({"error": f"No approved app named {name!r}. Available: {available}"})


def _run(cmds: list) -> str:
    """Each entry in `cmds` is either a bare path/command string (existing
    behavior, used by direct launch_app() calls) or a dict
    `{"path": str, "cwd": str | None, "args": list[str]}` (used by
    profiles.activate() to restore session state)."""
    launched: list[str] = []
    errors: list[str] = []
    for cmd in cmds:
        cwd = None
        args: list[str] = []
        if isinstance(cmd, dict):
            path = cmd["path"]
            cwd = cmd.get("cwd")
            args = list(cmd.get("args") or [])
        else:
            path = cmd

        try:
            if args or isinstance(cmd, dict):
                full_cmd = [path, *args]
                subprocess.Popen(full_cmd, cwd=cwd)
                launched.append(" ".join(str(c) for c in full_cmd))
            elif isinstance(cmd, list):
                subprocess.Popen(cmd, cwd=cwd)
                launched.append(" ".join(str(c) for c in cmd))
            elif sys.platform == "win32":
                # "start" goes through ShellExecute — finds apps via App Paths registry
                # (bare app names like "spotify" aren't on PATH but are in App Paths)
                subprocess.Popen(f'start "" "{cmd}"', shell=True, cwd=cwd)
                launched.append(cmd)
            else:
                subprocess.Popen(cmd.split(), cwd=cwd)
                launched.append(cmd)
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if errors:
        return json.dumps({"launched": launched, "errors": errors})
    return json.dumps({"launched": launched, "status": "ok"})
