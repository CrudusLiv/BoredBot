"""Tiny .env loader. No python-dotenv dep — keep it minimal.

Reads <project_root>/.env once on import (idempotent) and pushes any
KEY=VALUE pairs that aren't already in os.environ. Quoted values are
unquoted; lines starting with # are comments. Existing env vars win
(so a real shell export overrides .env)."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
ENV_PATH = PROJECT_DIR / ".env"

_loaded = False


def load_env() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


load_env()
