"""One-shot migration: copy runtime data from legacy .claude/data/ to %APPDATA%/Vesper/.

Called at startup (before Brain is constructed). Safe to call multiple times --
the .migrated_v1 marker prevents double-migration. Never overwrites existing files
in the destination.
"""
from __future__ import annotations

import shutil
from pathlib import Path


_LEGACY_FILES = ("brain_session.json", "voice_audit.jsonl", "voice_notices.jsonl")


def run_if_needed() -> None:
    from voice import config as cfg

    dst_dir = cfg.get_data_dir()
    marker = dst_dir / ".migrated_v1"
    if marker.exists():
        return

    src_dir = Path(__file__).resolve().parents[1] / ".claude" / "data"
    if not src_dir.exists():
        marker.touch()
        return

    dst_dir.mkdir(parents=True, exist_ok=True)
    for fname in _LEGACY_FILES:
        src = src_dir / fname
        dst = dst_dir / fname
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass

    marker.touch()
