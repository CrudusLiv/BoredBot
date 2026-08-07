"""Persisted allowlist of apps Vesper is permitted to launch by voice.

Storage: %APPDATA%\\Vesper\\approved_apps.json
  {"<alias>": {"path": "<resolved target path>", "approved_at": "<iso8601>"}}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _store_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "approved_apps.json"


def load() -> dict[str, dict[str, str]]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(data: dict[str, dict[str, str]]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def approve(path: str, alias: str) -> None:
    data = load()
    data[alias.lower()] = {
        "path": path,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    save(data)


def revoke(alias_or_path: str) -> bool:
    """Remove by alias (case-insensitive) or by matching path. Returns True if removed."""
    data = load()
    key = alias_or_path.lower()
    if key in data:
        del data[key]
        save(data)
        return True
    for alias, entry in list(data.items()):
        if entry.get("path", "").lower() == key:
            del data[alias]
            save(data)
            return True
    return False


def get_approved() -> dict[str, str]:
    """Return {alias: path} for all approved apps."""
    return {alias: entry["path"] for alias, entry in load().items()}
