"""Writer/loader for the packaged app's data-dir .env file.

The setup wizard collects API keys and, until now, only pushed them into
os.environ for the current process — they vanished on restart because
there was nowhere durable to persist them in a frozen build (the project
root .env used in dev doesn't exist inside a PyInstaller exe).

This module writes/reads voice.config.get_data_dir()/".env" instead — a
location that exists identically in both dev and frozen builds. It mirrors
the format and precedence rule of .claude/scripts/integrations/_env.py
(existing os.environ values always win over file values) but targets a
different path, so the two loaders are additive, not competing.
"""
from __future__ import annotations

import os
from pathlib import Path


def _default_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / ".env"


def write_env(updates: dict[str, str], path: Path | None = None) -> None:
    """Update/add KEY=value lines in the .env at `path` (default: data-dir .env).

    Only non-empty values in `updates` are written — callers pass whatever
    the user actually typed, so leaving a field blank never clobbers a key
    persisted on a previous run. All other lines (comments, unrelated keys,
    ordering) are preserved untouched, and duplicate keys are never created.
    Writes to a temp file and replaces it — atomic-enough for a single-user
    desktop app.
    """
    to_write = {k: v for k, v in updates.items() if v}
    if not to_write:
        return

    target = path or _default_path()
    lines: list[str] = []
    if target.exists():
        lines = target.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in to_write:
                out.append(f"{key}={to_write[key]}")
                seen.add(key)
                continue
        out.append(raw)

    for key, val in to_write.items():
        if key not in seen:
            out.append(f"{key}={val}")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(target)


def load_env(path: Path | None = None) -> None:
    """Push KEY=value pairs from the data-dir .env into os.environ.

    Existing os.environ values always win (same precedence rule as
    integrations._env.load_env) — call this as early as possible at startup
    so a persisted key fills the gap only when nothing else already set it.
    """
    target = path or _default_path()
    if not target.exists():
        return
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
