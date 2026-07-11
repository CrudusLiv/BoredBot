"""Persisted app-launch profiles — named groups of approved apps that can be
activated together, either by voice (confirmation-gated) or by a scheduled
heartbeat trigger (un-gated, since it's the user's own prior config firing).

Storage: %APPDATA%\\Vesper\\profiles.json
  {
    "<profile_id>": {
      "label": "Study Mode",
      "apps": [
        {"alias": "vscode", "cwd": "D:/GitHub/Vesper", "args": ["."]},
        {"alias": "spotify", "cwd": null, "args": []}
      ],
      "trigger": {"type": "time", "time": "18:00", "days": ["mon", ...]} | null,
      "created_at": "<iso8601>",
      "last_fired": "<iso8601 or null>"
    }
  }

Each entry in `apps` may be given as a bare alias string (back-compat) or a
dict with optional `cwd`/`args` session-restore state — `_normalize_app_entry()`
converts both forms to the dict shape before storage.

`trigger.type` may also be "context" with `signal: "idle_return"` and an
optional `min_idle_minutes` — fired by heartbeat.py's
_check_context_profiles() when the user returns from an idle stretch at
least that long. Time triggers are handled separately in
_check_profile_triggers(), which still skips anything but "time".

`trigger.type` may also be "process" with `exe: "<name>.exe"` and
`event: "launched" | "running"` — fired by heartbeat.py's
_check_process_triggers() from the per-poll process scan. "launched" fires
once when the exe first appears; "running" fires while it is present, with a
30-min per-profile cooldown. create() stores any trigger dict as-is, so no
validation change is needed here.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

# voice.tools/__init__.py does `from voice.tools.launch_app import launch_app`,
# which rebinds the `launch_app` attribute on the voice.tools package to that
# *function*, shadowing the submodule. importlib.import_module() resolves via
# sys.modules instead of attribute lookup, so this always gets the real module
# (needed so activate() calls launch_app._run(...) and tests can monkeypatch
# voice.profiles.launch_app._run directly).
launch_app = importlib.import_module("voice.tools.launch_app")


def _store_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "profiles.json"


def load() -> dict[str, dict]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(data: dict[str, dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_app_entry(entry: "str | dict") -> dict:
    """Accept either a bare alias string (back-compat) or a dict carrying
    optional launch state; always return the dict shape."""
    if isinstance(entry, str):
        return {"alias": entry, "cwd": None, "args": []}
    return {
        "alias": entry["alias"],
        "cwd": entry.get("cwd"),
        "args": list(entry.get("args") or []),
    }


def create(profile_id: str, label: str, apps: list, trigger: dict | None = None) -> None:
    """Create (or overwrite) a profile. Every alias in `apps` must already be
    approved in voice.approved_apps — this is the enforcement point that keeps
    profiles from embedding arbitrary commands. Each entry in `apps` may be a
    bare alias string or a dict with optional cwd/args (session-restore state)."""
    from voice import approved_apps

    normalized = [_normalize_app_entry(a) for a in apps]
    approved = approved_apps.get_approved()
    approved_lower = {alias.lower() for alias in approved}
    unknown = [a["alias"] for a in normalized if a["alias"].lower() not in approved_lower]
    if unknown:
        raise ValueError(f"Unknown/unapproved app alias(es): {', '.join(unknown)}")

    data = load()
    data[profile_id] = {
        "label": label,
        "apps": normalized,
        "trigger": trigger,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_fired": None,
    }
    save(data)


def update(profile_id: str, **fields) -> None:
    data = load()
    if profile_id not in data:
        raise KeyError(f"No such profile: {profile_id!r}")
    data[profile_id].update(fields)
    save(data)


def delete(profile_id: str) -> bool:
    data = load()
    if profile_id in data:
        del data[profile_id]
        save(data)
        return True
    return False


def get(profile_id: str) -> dict | None:
    return load().get(profile_id)


def find_by_name(name: str) -> tuple[str, dict] | None:
    """Case-insensitive match against `label` first, then the profile id."""
    data = load()
    key = name.lower()
    for profile_id, profile in data.items():
        if profile.get("label", "").lower() == key:
            return profile_id, profile
    for profile_id, profile in data.items():
        if profile_id.lower() == key:
            return profile_id, profile
    return None


def mark_fired(profile_id: str) -> None:
    data = load()
    if profile_id in data:
        data[profile_id]["last_fired"] = datetime.now(timezone.utc).isoformat()
        save(data)


def set_app_state(name: str, alias: str, *, cwd: str | None = None, args: list[str] | None = None) -> None:
    """Update the cwd/args launch state for one app inside a profile,
    matched case-insensitively by profile label or id, then by app alias."""
    found = find_by_name(name)
    if found is None:
        raise KeyError(f"No profile named {name!r}")
    profile_id, profile = found

    apps = [_normalize_app_entry(a) for a in profile.get("apps", [])]
    for entry in apps:
        if entry["alias"].lower() == alias.lower():
            if cwd is not None:
                entry["cwd"] = cwd
            if args is not None:
                entry["args"] = list(args)
            update(profile_id, apps=apps)
            return
    raise KeyError(f"No app named {alias!r} in profile {name!r}")


def activate(name: str) -> dict:
    """The single shared activation primitive, used by BOTH the
    confirmation-gated voice tool and the un-gated heartbeat auto-fire.

    Does NOT itself perform any confirmation/safety check — gating happens
    one layer up, differently per caller (voice tool goes through normal
    brain.py -> safety.py dispatch gating; heartbeat calls this directly).
    """
    from voice import approved_apps

    found = find_by_name(name)
    if found is None:
        return {"error": f"No profile named {name!r}"}
    profile_id, profile = found

    approved = approved_apps.get_approved()
    approved_lower = {alias.lower(): path for alias, path in approved.items()}

    launched: list[str] = []
    errors: list[str] = []
    for entry in profile.get("apps", []):
        entry = _normalize_app_entry(entry) if isinstance(entry, str) else entry
        alias = entry["alias"]
        path = approved_lower.get(alias.lower())
        if path is None:
            errors.append(f"{alias}: not approved")
            continue
        result = json.loads(launch_app._run([{"path": path, "cwd": entry.get("cwd"), "args": entry.get("args") or []}]))
        launched.extend(result.get("launched", []))
        errors.extend(result.get("errors", []))

    if launched:
        mark_fired(profile_id)

    return {"profile": profile.get("label", profile_id), "launched": launched, "errors": errors}
