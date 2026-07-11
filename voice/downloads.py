"""Downloads triage: notice new files in the user's Downloads folder and,
on explicit approval, move them into the vault inbox for the existing
pipeline to classify. Pure functions — no heartbeat/FastAPI imports here."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

PARTIAL_SUFFIXES = {".crdownload", ".part", ".tmp", ".download"}
DEFAULT_EXTS = [".pdf", ".pptx", ".ppt", ".docx", ".png", ".jpg", ".jpeg"]
SEEN_FILE = "downloads_seen.json"


def default_folders() -> list[str]:
    return [str(Path.home() / "Downloads")]


def scan_new(folders: list[str], exts: list[str], seen: dict,
             min_age_seconds: int = 20, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    allow = {e.lower() for e in exts}
    out: list[dict] = []
    for folder in folders:
        root = Path(folder)
        try:
            entries = list(root.iterdir())
        except OSError:
            continue                      # missing/inaccessible folder: skip
        for p in entries:
            try:
                if not p.is_file():
                    continue
                suffix = p.suffix.lower()
                if suffix in PARTIAL_SUFFIXES or suffix not in allow:
                    continue
                st = p.stat()
                if now - st.st_mtime < min_age_seconds:
                    continue              # still being written
                key = str(p)
                if seen.get(key) == st.st_mtime:
                    continue              # already suggested this version
                out.append({
                    "path": key, "name": p.name, "size": st.st_size,
                    "mtime": st.st_mtime, "dest": "inbox",
                })
            except OSError:
                continue                  # vanished/locked mid-scan: skip
    out.sort(key=lambda c: c["path"])
    return out
