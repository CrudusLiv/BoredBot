"""Append-only JSONL audit log for all voice turns and tool calls.

Written to get_data_dir()/voice_audit.jsonl.
Schema per line: {"ts": "<ISO8601>", "role": "user|assistant|tool|stt", "content": "...", ["tool": "name"], ["outcome": "cancelled|timeout|paused|..."], ["meta": {...}]}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_MAX_CONTENT = 500
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB cap per file
_KEEP_LINES = 1000              # lines retained after trimming
_ROTATE_EVERY = 50              # check size every N writes
_write_count = 0


def _log_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "voice_audit.jsonl"


def _notices_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "voice_notices.jsonl"


def _maybe_rotate(path: Path) -> None:
    try:
        if path.stat().st_size < _MAX_BYTES:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _KEEP_LINES:
            path.write_text("\n".join(lines[-_KEEP_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def log(role: str, content: str, tool_name: str | None = None, outcome: str | None = None,
        meta: dict | None = None) -> None:
    """Append one audit entry (non-fatal on I/O error)."""
    global _write_count
    from voice import config as cfg
    entry: dict = {
        "ts": datetime.now(cfg.get_timezone()).isoformat(),
        "role": role,
        "content": content[:_MAX_CONTENT],
    }
    if tool_name:
        entry["tool"] = tool_name
    if outcome is not None:
        entry["outcome"] = outcome
    if meta:
        entry["meta"] = meta
    try:
        log_p = _log_path()
        log_p.parent.mkdir(parents=True, exist_ok=True)
        with log_p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _write_count += 1
        if _write_count % _ROTATE_EVERY == 0:
            _maybe_rotate(log_p)
            _maybe_rotate(_notices_path())
    except OSError:
        pass
